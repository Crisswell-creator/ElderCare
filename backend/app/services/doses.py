"""Dose lifecycle: generation, status rules and confirmation.

States are kept distinct on purpose:
  scheduled   - upcoming, or due and still inside the grace period
  taken       - someone confirmed it was taken (who, when and from where are recorded)
  skipped     - someone confirmed it was deliberately not taken (optional reason)
  unconfirmed - grace period passed with no confirmation; *not* assumed missed
  missed      - the configured missed window closed with no confirmation
  cancelled   - the schedule changed, or the medicine was paused/discontinued
Opening a reminder never changes a dose; only an explicit confirmation does.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain import (
    DoseStatus,
    InventoryKind,
    MedicationStatus,
    NotificationStatus,
    Role,
    ScheduleType,
)
from app.errors import AppError, Conflict
from app.models import DoseEvent, Medication, Notification, Patient, User
from app.services import inventory
from app.services.schedule import Slot, occurrences

HORIZON = timedelta(hours=36)
LOOKBACK = timedelta(hours=24)
EARLIEST_CONFIRM = timedelta(hours=3)  # a dose may be confirmed up to 3h before it is due
LATEST_CONFIRM = timedelta(hours=24)
UNDO_WINDOW = timedelta(hours=12)
SNOOZE_CHOICES = (10, 15, 30)
MAX_SNOOZES = 3


def slots_of(med: Medication) -> list[Slot]:
    return [Slot(t.local_time, t.days_mask) for t in med.times]


def materialize(db: Session, now: datetime, medication_ids: list[int] | None = None) -> int:
    """Creates missing dose rows for active scheduled medicines in [now-24h, now+36h).
    Idempotent: existing rows are left alone (a unique key backs this up), and a future
    dose cancelled by a schedule edit is revived if the new schedule wants it again."""
    stmt = (
        select(Medication, Patient.timezone)
        .join(Patient, Patient.id == Medication.patient_id)
        .where(
            Medication.status == MedicationStatus.ACTIVE,
            Medication.schedule_type == ScheduleType.SCHEDULED,
            Medication.archived_at.is_(None),
        )
    )
    if medication_ids is not None:
        stmt = stmt.where(Medication.id.in_(medication_ids))
    meds = db.execute(stmt).unique().all()
    if not meds:
        return 0
    window_end = now + HORIZON
    existing: dict[tuple[int, datetime], DoseEvent] = {
        (d.medication_id, d.scheduled_at): d
        for d in db.scalars(
            select(DoseEvent).where(
                DoseEvent.medication_id.in_([m.id for m, _ in meds]),
                DoseEvent.scheduled_at >= now - LOOKBACK,
                DoseEvent.scheduled_at < window_end,
                DoseEvent.as_needed.is_(False),
            )
        )
    }
    created = 0
    for med, tz in meds:
        start = max(now - LOOKBACK, med.schedule_anchor_at)
        for occ in occurrences(slots_of(med), tz, med.start_date, med.end_date, start, window_end):
            row = existing.get((med.id, occ.scheduled_at))
            if row is None:
                db.add(
                    DoseEvent(
                        patient_id=med.patient_id,
                        medication_id=med.id,
                        scheduled_at=occ.scheduled_at,
                        local_date=occ.local_date,
                        local_time=occ.local_time,
                        dose_amount=med.dose_amount,
                    )
                )
                created += 1
            elif (
                row.status == DoseStatus.CANCELLED
                and row.scheduled_at > now
                and row.confirmed_at is None
            ):
                row.status = DoseStatus.SCHEDULED
                row.cancelled_reason = ""
                row.dose_amount = med.dose_amount
    db.flush()
    return created


def cancel_future(db: Session, med: Medication, now: datetime, reason: str) -> int:
    result = db.execute(
        update(DoseEvent)
        .where(
            DoseEvent.medication_id == med.id,
            DoseEvent.scheduled_at > now,
            DoseEvent.status == DoseStatus.SCHEDULED,
        )
        .values(status=DoseStatus.CANCELLED, cancelled_reason=reason, status_changed_at=now)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def due_transitions(dose: DoseEvent, patient: Patient, now: datetime) -> str | None:
    """The status a dose should move to now, or None. Pure function of time and rules."""
    grace_end = dose.scheduled_at + timedelta(minutes=patient.dose_grace_minutes)
    missed_at = dose.scheduled_at + timedelta(minutes=patient.missed_after_minutes)
    if dose.status in (DoseStatus.SCHEDULED, DoseStatus.UNCONFIRMED) and now >= missed_at:
        return DoseStatus.MISSED
    if dose.status == DoseStatus.SCHEDULED and now >= grace_end:
        return DoseStatus.UNCONFIRMED
    return None


def _source(actor_role: str) -> str:
    return "elder" if actor_role == Role.ELDER else actor_role


def _ensure_confirmable(dose: DoseEvent, now: datetime) -> None:
    if dose.status not in (DoseStatus.SCHEDULED, DoseStatus.UNCONFIRMED, DoseStatus.MISSED):
        raise Conflict("This dose has already been recorded.")
    if now < dose.scheduled_at - EARLIEST_CONFIRM:
        raise AppError("This dose is not due yet. You can confirm it up to 3 hours early.")
    if now > dose.scheduled_at + LATEST_CONFIRM:
        raise AppError("This dose is more than 24 hours old and can no longer be changed.")


def mark_taken(db: Session, dose: DoseEvent, actor: User, actor_role: str, now: datetime) -> None:
    _ensure_confirmable(dose, now)
    dose.status = DoseStatus.TAKEN
    dose.confirmed_at = now
    dose.confirmed_by = actor  # relationship, so the response shows the name immediately
    dose.confirmation_source = _source(actor_role)
    dose.status_changed_at = now
    dose.snoozed_until = None
    db.flush()
    inventory.apply(
        db,
        dose.medication,
        InventoryKind.DOSE_TAKEN,
        delta=-dose.dose_amount,
        actor=actor,
        note="Dose taken",
        dose_event_id=dose.id,
    )
    suppress_alerts_if_resolved(db, dose)


def mark_skipped(
    db: Session, dose: DoseEvent, actor: User, actor_role: str, now: datetime, reason: str
) -> None:
    _ensure_confirmable(dose, now)
    dose.status = DoseStatus.SKIPPED
    dose.confirmed_at = now
    dose.confirmed_by = actor  # relationship, so the response shows the name immediately
    dose.confirmation_source = _source(actor_role)
    dose.skip_reason = reason.strip()[:200]
    dose.status_changed_at = now
    dose.snoozed_until = None
    suppress_alerts_if_resolved(db, dose)


def undo(
    db: Session, dose: DoseEvent, actor: User, is_elder: bool, patient: Patient, now: datetime
) -> None:
    if dose.status not in (DoseStatus.TAKEN, DoseStatus.SKIPPED) or dose.confirmed_at is None:
        raise Conflict("Only a taken or skipped dose can be undone.")
    if dose.as_needed:
        raise Conflict("As-needed records cannot be undone; add a correction note instead.")
    if not is_elder and dose.confirmed_by_user_id != actor.id:
        raise AppError("Only the person who recorded this dose, or the elder, can undo it.")
    if now - dose.confirmed_at > UNDO_WINDOW:
        raise AppError("This record is more than 12 hours old and can no longer be undone.")
    if dose.status == DoseStatus.TAKEN:
        inventory.apply(
            db,
            dose.medication,
            InventoryKind.DOSE_REVERTED,
            delta=dose.dose_amount,
            actor=actor,
            note="Dose record undone",
            dose_event_id=dose.id,
        )
    dose.status = DoseStatus.SCHEDULED
    dose.confirmed_at = None
    dose.confirmed_by = None
    dose.confirmation_source = ""
    dose.skip_reason = ""
    dose.status_changed_at = now
    dose.status = due_transitions(dose, patient, now) or DoseStatus.SCHEDULED


def snooze(dose: DoseEvent, patient: Patient, minutes: int, now: datetime) -> None:
    if minutes not in SNOOZE_CHOICES:
        raise AppError("Choose 10, 15 or 30 minutes.")
    if dose.status != DoseStatus.SCHEDULED or now < dose.scheduled_at - timedelta(minutes=30):
        raise AppError("Only a dose that is due now can be snoozed.")
    if dose.snooze_count >= MAX_SNOOZES:
        raise AppError("This reminder has been snoozed the maximum number of times.")
    grace_end = dose.scheduled_at + timedelta(minutes=patient.dose_grace_minutes)
    dose.snoozed_until = min(now + timedelta(minutes=minutes), grace_end)
    dose.snooze_count += 1


def record_as_needed(
    db: Session,
    med: Medication,
    actor: User,
    actor_role: str,
    now: datetime,
    amount: Decimal | None,
) -> DoseEvent:
    if med.schedule_type != ScheduleType.AS_NEEDED:
        raise AppError("This medicine has a fixed schedule; confirm its scheduled doses.")
    if med.status != MedicationStatus.ACTIVE:
        raise AppError("This medicine is not active.")
    patient = db.get(Patient, med.patient_id)
    if patient is None:
        raise AppError("Profile not found.")
    local = now.astimezone(ZoneInfo(patient.timezone))
    dose = DoseEvent(
        patient_id=med.patient_id,
        medication_id=med.id,
        scheduled_at=now,
        local_date=local.date(),
        local_time=local.time().replace(microsecond=0),
        dose_amount=amount if amount is not None else med.dose_amount,
        as_needed=True,
        status=DoseStatus.TAKEN,
        confirmed_at=now,
        confirmed_by=actor,
        confirmation_source=_source(actor_role),
        status_changed_at=now,
    )
    db.add(dose)
    db.flush()
    inventory.apply(
        db,
        med,
        InventoryKind.DOSE_TAKEN,
        delta=-dose.dose_amount,
        actor=actor,
        note="As-needed dose",
        dose_event_id=dose.id,
    )
    return dose


def suppress_alerts_if_resolved(db: Session, dose: DoseEvent) -> None:
    """When every dose in a reminder slot is resolved, queued-but-unsent reminder and
    escalation emails for that slot are withdrawn, so nobody is alerted after the fact."""
    open_left = db.scalar(
        select(DoseEvent.id)
        .where(
            DoseEvent.patient_id == dose.patient_id,
            DoseEvent.scheduled_at == dose.scheduled_at,
            DoseEvent.status.in_([DoseStatus.SCHEDULED, DoseStatus.UNCONFIRMED]),
            DoseEvent.id != dose.id,
        )
        .limit(1)
    )
    if open_left is not None:
        return
    slot = dose.scheduled_at.isoformat()
    for prefix in ("remind", "escalate"):
        db.execute(
            update(Notification)
            .where(
                Notification.dedupe_key.like(f"{prefix}:{dose.patient_id}:{slot}:%"),
                Notification.status == NotificationStatus.PENDING,
            )
            .values(
                status=NotificationStatus.SUPPRESSED,
                last_error="Withdrawn: dose was recorded before delivery",
            )
            .execution_options(synchronize_session=False)
        )
