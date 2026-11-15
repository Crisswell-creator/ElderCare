"""The reminder engine. `tick(now)` is safe to run as often as wanted, from any number of
instances: every step is idempotent (unique dose keys, unique notification dedupe keys)
and all state lives in the database, so nothing is lost across restarts or deploys.

Cloud Scheduler calls it every 5 minutes through POST /internal/jobs/tick.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import (
    AppointmentStatus,
    DoseStatus,
    MedicationStatus,
    MembershipStatus,
    NotificationKind,
    Permission,
    Role,
)
from app.logging_setup import log_event
from app.models import Appointment, DoseEvent, Medication, Membership, Patient
from app.services import doses, notify, throttle
from app.services.schedule import daily_use, stock_estimate

logger = logging.getLogger("eldercare.engine")


@dataclass
class TickReport:
    doses_created: int = 0
    became_unconfirmed: int = 0
    became_missed: int = 0
    queued: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    delivery: dict[str, int] = field(default_factory=dict)


def _members(db: Session, patient_ids: set[int]) -> dict[int, list[Membership]]:
    out: dict[int, list[Membership]] = defaultdict(list)
    if patient_ids:
        for m in db.scalars(
            select(Membership).where(
                Membership.patient_id.in_(patient_ids), Membership.status == MembershipStatus.ACTIVE
            )
        ):
            out[m.patient_id].append(m)
    return out


def _can(m: Membership, perm: Permission) -> bool:
    return m.role == Role.ELDER or perm in (m.permissions or [])


def _first_name(p: Patient) -> str:
    return p.first_name


def _clock(at: datetime, tz: str) -> str:
    return at.astimezone(ZoneInfo(tz)).strftime("%I:%M %p").lstrip("0")


def tick(db: Session, now: datetime) -> TickReport:
    report = TickReport()
    report.doses_created = doses.materialize(db, now)
    db.commit()
    _advance_dose_states(db, now, report)
    _dose_reminders(db, now, report)
    _appointment_reminders(db, now, report)
    _low_stock(db, now, report)
    db.commit()
    report.delivery = notify.deliver_pending(db, now)
    throttle.purge_older_than(db, days=7)
    db.commit()
    log_event(
        logger,
        logging.INFO,
        "reminder tick complete",
        doses_created=report.doses_created,
        unconfirmed=report.became_unconfirmed,
        missed=report.became_missed,
        queued=dict(report.queued),
        delivery=report.delivery,
    )
    return report


def _advance_dose_states(db: Session, now: datetime, report: TickReport) -> None:
    rows = (
        db.execute(
            select(DoseEvent, Patient)
            .join(Patient, Patient.id == DoseEvent.patient_id)
            .where(
                DoseEvent.status.in_([DoseStatus.SCHEDULED, DoseStatus.UNCONFIRMED]),
                DoseEvent.scheduled_at <= now - timedelta(minutes=15),
            )
        )
        .unique()
        .all()
    )
    for dose, patient in rows:
        new = doses.due_transitions(dose, patient, now)
        if new is None:
            continue
        if new == DoseStatus.UNCONFIRMED:
            report.became_unconfirmed += 1
        else:
            report.became_missed += 1
        dose.status = new
        dose.status_changed_at = now
    db.flush()
    _escalate_unconfirmed(db, now, report)


def _escalate_unconfirmed(db: Session, now: datetime, report: TickReport) -> None:
    """Once the grace period has passed with no confirmation, tell the people the elder
    authorised to follow medicines: one message per time slot, never per pill. This scans
    every currently-unconfirmed dose rather than only fresh transitions, so a status set by
    a screen refresh between ticks still escalates; the dedupe key keeps it to one email."""
    rows = (
        db.execute(
            select(DoseEvent, Patient)
            .join(Patient, Patient.id == DoseEvent.patient_id)
            .where(
                DoseEvent.status == DoseStatus.UNCONFIRMED,
                DoseEvent.scheduled_at >= now - timedelta(hours=12),
            )
        )
        .unique()
        .all()
    )
    slots: dict[tuple[int, datetime], int] = defaultdict(int)
    patients: dict[int, Patient] = {}
    for dose, patient in rows:
        slots[(patient.id, dose.scheduled_at)] += 1
        patients[patient.id] = patient
    members = _members(db, set(patients))
    for (pid, slot), count in slots.items():
        patient = patients[pid]
        name = _first_name(patient)
        for m in members[pid]:
            if m.role == Role.ELDER or not m.notify_escalations:
                continue
            if not (_can(m, Permission.CONFIRM_DOSES) or _can(m, Permission.VIEW_MEDICATIONS)):
                continue
            queued = notify.enqueue(
                db,
                recipient=m.user,
                kind=NotificationKind.DOSE_ESCALATION,
                dedupe_key=f"escalate:{pid}:{slot.isoformat()}:{m.user_id}",
                subject="A scheduled dose has not been confirmed",
                paragraphs=[
                    f"{count} dose{'s' if count > 1 else ''} scheduled for {name} at "
                    f"{_clock(slot, patient.timezone)} "
                    f"{'have' if count > 1 else 'has'} not been confirmed yet.",
                    "This is a routine check-in, not an emergency alert. The dose may have "
                    "been taken without being recorded. If you can, check in with "
                    f"{name} and record what happened in ElderCare.",
                ],
                link_path=f"/p/{pid}/today",
                patient_id=pid,
                send_email=m.user.email_verified_at is not None,
                now=now,
            )
            report.queued["escalation"] += int(queued)
    db.flush()


def _dose_reminders(db: Session, now: datetime, report: TickReport) -> None:
    rows = (
        db.execute(
            select(DoseEvent, Patient)
            .join(Patient, Patient.id == DoseEvent.patient_id)
            .where(
                DoseEvent.status == DoseStatus.SCHEDULED,
                DoseEvent.scheduled_at <= now,
                DoseEvent.scheduled_at > now - timedelta(hours=4),
            )
        )
        .unique()
        .all()
    )
    slots: dict[tuple[int, datetime, int], list[DoseEvent]] = defaultdict(list)
    patients: dict[int, Patient] = {}
    for dose, patient in rows:
        grace_end = dose.scheduled_at + timedelta(minutes=patient.dose_grace_minutes)
        if now >= grace_end:
            continue
        if dose.snoozed_until is not None:
            if now < dose.snoozed_until:
                continue
            round_ = dose.snooze_count  # each snooze earns one new reminder
        else:
            round_ = 0
        slots[(patient.id, dose.scheduled_at, round_)].append(dose)
        patients[patient.id] = patient
    members = _members(db, set(patients))
    for (pid, slot, round_), slot_doses in slots.items():
        patient = patients[pid]
        count = len(slot_doses)
        for m in members[pid]:
            if not m.notify_dose_reminders or not _can(m, Permission.VIEW_MEDICATIONS):
                continue
            is_elder = m.role == Role.ELDER
            queued = notify.enqueue(
                db,
                recipient=m.user,
                kind=NotificationKind.DOSE_REMINDER,
                dedupe_key=f"remind:{pid}:{slot.isoformat()}:{m.user_id}:{round_}",
                subject="Time for a scheduled dose"
                if is_elder
                else f"Dose reminder for {_first_name(patient)}",
                paragraphs=[
                    (
                        f"It's time for {count} scheduled dose{'s' if count > 1 else ''} "
                        f"({_clock(slot, patient.timezone)})."
                        if is_elder
                        else f"{_first_name(patient)} has {count} dose{'s' if count > 1 else ''} "
                        f"scheduled at {_clock(slot, patient.timezone)}."
                    ),
                    "Open ElderCare to see which medicine and to record it as taken or "
                    "skipped. Opening this email does not record anything.",
                ],
                link_path=f"/p/{pid}/today",
                patient_id=pid,
                send_email=m.user.email_verified_at is not None,
                now=now,
            )
            report.queued["dose_reminder"] += int(queued)
    db.flush()


def _appointment_reminders(db: Session, now: datetime, report: TickReport) -> None:
    rows = (
        db.execute(
            select(Appointment, Patient)
            .join(Patient, Patient.id == Appointment.patient_id)
            .where(
                Appointment.status == AppointmentStatus.SCHEDULED,
                Appointment.starts_at > now,
                Appointment.starts_at <= now + timedelta(days=8),
            )
        )
        .unique()
        .all()
    )
    due: list[tuple[Appointment, Patient, int]] = []
    for appt, patient in rows:
        minutes_left = (appt.starts_at - now).total_seconds() / 60
        passed = [o for o in (appt.reminder_offsets or []) if o >= minutes_left]
        if passed:
            # Only the nearest reminder whose time has come; earlier ones that were missed
            # (e.g. appointment booked yesterday for today) are not sent late.
            due.append((appt, patient, min(passed)))
    members = _members(db, {p.id for _, p, _ in due})
    for appt, patient, offset in due:
        when = appt.starts_at.astimezone(ZoneInfo(patient.timezone))
        for m in members[patient.id]:
            if not m.notify_appointments or not _can(m, Permission.VIEW_APPOINTMENTS):
                continue
            queued = notify.enqueue(
                db,
                recipient=m.user,
                kind=NotificationKind.APPOINTMENT_REMINDER,
                dedupe_key=f"appt:{appt.id}:{appt.starts_at.isoformat()}:{offset}:{m.user_id}",
                subject="Upcoming appointment reminder",
                paragraphs=[
                    ("You have" if m.role == Role.ELDER else f"{_first_name(patient)} has")
                    + f" an appointment on {when.strftime('%A %d %B')} at "
                    f"{when.strftime('%I:%M %p').lstrip('0')}.",
                    "Open ElderCare for the location and any questions you planned to ask.",
                ],
                link_path=f"/p/{patient.id}/appointments",
                patient_id=patient.id,
                send_email=m.user.email_verified_at is not None,
                now=now,
            )
            report.queued["appointment_reminder"] += int(queued)
    db.flush()


def _low_stock(db: Session, now: datetime, report: TickReport) -> None:
    rows = (
        db.execute(
            select(Medication, Patient)
            .join(Patient, Patient.id == Medication.patient_id)
            .where(
                Medication.status == MedicationStatus.ACTIVE,
                Medication.archived_at.is_(None),
                Medication.quantity_on_hand.is_not(None),
            )
        )
        .unique()
        .all()
    )
    low: list[tuple[Medication, Patient, Decimal]] = []
    for med, patient in rows:
        today = now.astimezone(ZoneInfo(patient.timezone)).date()
        days, _ = stock_estimate(
            med.quantity_on_hand, daily_use(doses.slots_of(med), med.dose_amount), today
        )
        if days is not None and days <= med.refill_threshold_days:
            low.append((med, patient, days))
    members = _members(db, {p.id for _, p, _ in low})
    week = now.strftime("%G-W%V")  # at most one warning per medicine per week
    for med, patient, days in low:
        for m in members[patient.id]:
            if not m.notify_low_stock:
                continue
            if not (_can(m, Permission.MANAGE_MEDICATIONS) or _can(m, Permission.CONFIRM_DOSES)):
                continue
            queued = notify.enqueue(
                db,
                recipient=m.user,
                kind=NotificationKind.LOW_STOCK,
                dedupe_key=f"lowstock:{med.id}:{week}:{m.user_id}",
                subject="A medicine may need a refill soon",
                paragraphs=[
                    f"Based on the recorded stock and schedule, one of "
                    f"{'your' if m.role == Role.ELDER else _first_name(patient) + chr(8217) + 's'}"
                    f" medicines may run out in about {int(days)} day{'s' if days != 1 else ''}.",
                    "This is an estimate. Open ElderCare to see which medicine and to record "
                    "a refill or correct the count.",
                ],
                link_path=f"/p/{patient.id}/medications/{med.id}",
                patient_id=patient.id,
                send_email=m.user.email_verified_at is not None,
                now=now,
            )
            report.queued["low_stock"] += int(queued)
    db.flush()
