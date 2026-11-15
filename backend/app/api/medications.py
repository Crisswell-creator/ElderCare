"""Medicines, schedules, the stock ledger, and dose confirmation."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import PatientAccess, requires
from app.domain import DoseStatus, InventoryKind, MedicationStatus, Permission, ScheduleType
from app.errors import AppError, Forbidden, NotFound
from app.models import DoseEvent, InventoryEvent, Medication, MedicationTime, Patient
from app.services import audit, doses, inventory
from app.services.schedule import ALL_DAYS, daily_use, stock_estimate

router = APIRouter(prefix="/api/patients/{patient_id}", tags=["medications"])

FORMS = Literal[
    "tablet", "capsule", "liquid", "injection", "inhaler", "drops", "patch", "cream", "other"
]


class TimeIn(BaseModel):
    local_time: time
    days: list[Annotated[int, Field(ge=0, le=6)]] = Field(default_factory=lambda: list(range(7)))

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("Pick at least one day")
        return sorted(set(v))

    @property
    def mask(self) -> int:
        return sum(1 << d for d in self.days)


class MedicationIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    strength: Annotated[str, Field(max_length=60)] = ""
    form: FORMS = "tablet"
    dose_amount: Decimal = Field(gt=0, le=1000, decimal_places=2)
    dose_unit: Annotated[str, Field(min_length=1, max_length=24)] = "tablet"
    instructions: Annotated[str, Field(max_length=1000)] = ""
    schedule_type: ScheduleType = ScheduleType.SCHEDULED
    start_date: date
    end_date: date | None = None
    prescriber: Annotated[str, Field(max_length=120)] = ""
    refill_threshold_days: int = Field(default=7, ge=0, le=90)
    times: list[TimeIn] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _check(self) -> MedicationIn:
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date must be on or after the start date")
        if self.schedule_type == ScheduleType.SCHEDULED and not self.times:
            raise ValueError("Add at least one time for a scheduled medicine")
        if self.schedule_type == ScheduleType.AS_NEEDED:
            self.times = []
        stamps = [t.local_time.replace(second=0, microsecond=0) for t in self.times]
        if len(set(stamps)) != len(stamps):
            raise ValueError("Each dose time can only appear once")
        return self


class MedicationCreate(MedicationIn):
    initial_quantity: Decimal | None = Field(default=None, ge=0, le=100000)


class TimeOut(BaseModel):
    local_time: str
    days: list[int]


class MedicationOut(BaseModel):
    id: int
    name: str
    strength: str
    form: str
    dose_amount: float
    dose_unit: str
    instructions: str
    schedule_type: str
    start_date: date
    end_date: date | None
    status: str
    status_reason: str
    prescriber: str
    refill_threshold_days: int
    times: list[TimeOut]
    quantity_on_hand: float | None
    daily_use: float
    days_remaining: float | None
    estimated_run_out: date | None
    low_stock: bool
    archived: bool


class InventoryIn(BaseModel):
    kind: Literal["refill", "correction"]
    quantity: Decimal = Field(ge=0, le=100000, decimal_places=2)
    note: Annotated[str, Field(max_length=300)] = ""


class InventoryOut(BaseModel):
    id: int
    kind: str
    quantity_delta: float
    quantity_after: float
    note: str
    actor_name: str | None
    created_at: datetime


class MedicationDetail(BaseModel):
    medication: MedicationOut
    inventory: list[InventoryOut]


class StatusIn(BaseModel):
    status: MedicationStatus
    reason: Annotated[str, Field(max_length=200)] = ""


class DoseOut(BaseModel):
    id: int
    medication_id: int
    medication_name: str
    strength: str
    dose_amount: float
    dose_unit: str
    instructions: str
    scheduled_at: datetime
    local_date: date
    local_time: str
    status: str
    as_needed: bool
    confirmed_at: datetime | None
    confirmed_by: str | None
    confirmation_source: str
    skip_reason: str
    snoozed_until: datetime | None
    cancelled_reason: str


class SkipIn(BaseModel):
    reason: Annotated[str, Field(max_length=200)] = ""


class SnoozeIn(BaseModel):
    minutes: Literal[10, 15, 30]


class AsNeededIn(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, le=1000)


def med_out(med: Medication, today: date) -> MedicationOut:
    slots = doses.slots_of(med)
    per_day = (
        daily_use(slots, med.dose_amount) if med.status == MedicationStatus.ACTIVE else Decimal(0)
    )
    days_left, run_out = stock_estimate(med.quantity_on_hand, per_day, today)
    return MedicationOut(
        id=med.id,
        name=med.name,
        strength=med.strength,
        form=med.form,
        dose_amount=float(med.dose_amount),
        dose_unit=med.dose_unit,
        instructions=med.instructions,
        schedule_type=med.schedule_type,
        start_date=med.start_date,
        end_date=med.end_date,
        status=med.status,
        status_reason=med.status_reason,
        prescriber=med.prescriber,
        refill_threshold_days=med.refill_threshold_days,
        times=[
            TimeOut(
                local_time=t.local_time.strftime("%H:%M"),
                days=[d for d in range(7) if t.days_mask & (1 << d)],
            )
            for t in med.times
        ],
        quantity_on_hand=float(med.quantity_on_hand) if med.quantity_on_hand is not None else None,
        daily_use=float(per_day),
        days_remaining=float(days_left) if days_left is not None else None,
        estimated_run_out=run_out,
        low_stock=days_left is not None and days_left <= med.refill_threshold_days,
        archived=med.archived_at is not None,
    )


def dose_out(d: DoseEvent) -> DoseOut:
    m = d.medication
    return DoseOut(
        id=d.id,
        medication_id=m.id,
        medication_name=m.name,
        strength=m.strength,
        dose_amount=float(d.dose_amount),
        dose_unit=m.dose_unit,
        instructions=m.instructions,
        scheduled_at=d.scheduled_at,
        local_date=d.local_date,
        local_time=d.local_time.strftime("%H:%M"),
        status=d.status,
        as_needed=d.as_needed,
        confirmed_at=d.confirmed_at,
        confirmed_by=d.confirmed_by.full_name if d.confirmed_by else None,
        confirmation_source=d.confirmation_source,
        skip_reason=d.skip_reason,
        snoozed_until=d.snoozed_until,
        cancelled_reason=d.cancelled_reason,
    )


def local_today(patient: Patient) -> date:
    return utcnow().astimezone(ZoneInfo(patient.timezone)).date()


def _get_med(db: Session, access: PatientAccess, med_id: int) -> Medication:
    med = db.get(Medication, med_id)
    if med is None or med.patient_id != access.patient.id:
        raise NotFound("That medicine was not found.")
    return med


def _set_times(med: Medication, times: list[TimeIn]) -> None:
    """Updates rows in place by time of day. Replacing the collection wholesale would insert
    the new rows before deleting the old ones and trip the (medication, time) unique key."""
    wanted = {t.local_time.replace(second=0, microsecond=0): t.mask or ALL_DAYS for t in times}
    for row in list(med.times):
        if row.local_time in wanted:
            row.days_mask = wanted.pop(row.local_time)
        else:
            med.times.remove(row)
    med.times.extend(MedicationTime(local_time=k, days_mask=v) for k, v in wanted.items())
    med.times.sort(key=lambda r: r.local_time)


def _schedule_signature(med: Medication) -> tuple[object, ...]:
    return (
        med.schedule_type,
        med.start_date,
        med.end_date,
        med.dose_amount,
        tuple((t.local_time, t.days_mask) for t in med.times),
    )


@router.get("/medications", response_model=list[MedicationOut])
def list_medications(
    include_inactive: bool = False,
    access: PatientAccess = Depends(requires(Permission.VIEW_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> list[MedicationOut]:
    stmt = select(Medication).where(
        Medication.patient_id == access.patient.id, Medication.archived_at.is_(None)
    )
    if not include_inactive:
        stmt = stmt.where(Medication.status != MedicationStatus.DISCONTINUED)
    today = local_today(access.patient)
    return [med_out(m, today) for m in db.scalars(stmt.order_by(Medication.name))]


@router.post("/medications", response_model=MedicationOut, status_code=status.HTTP_201_CREATED)
def create_medication(
    body: MedicationCreate,
    access: PatientAccess = Depends(requires(Permission.MANAGE_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> MedicationOut:
    now = utcnow()
    med = Medication(
        patient_id=access.patient.id,
        created_by_user_id=access.user.id,
        schedule_anchor_at=now,
        **body.model_dump(exclude={"times", "initial_quantity"}),
    )
    _set_times(med, body.times)
    db.add(med)
    db.flush()
    if body.initial_quantity is not None:
        inventory.apply(
            db,
            med,
            InventoryKind.INITIAL,
            absolute=body.initial_quantity,
            actor=access.user,
            note="Starting count",
        )
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="medication.created",
        entity_type="medication",
        entity_id=med.id,
        summary=f"{access.user.full_name} added {med.name} {med.strength}".strip(),
        details={"times": [t.local_time.strftime("%H:%M") for t in med.times]},
    )
    doses.materialize(db, now, [med.id])
    invalidate_refresh(access.patient.id)
    db.commit()
    return med_out(med, local_today(access.patient))


@router.get("/medications/{med_id}", response_model=MedicationDetail)
def get_medication(
    med_id: int,
    access: PatientAccess = Depends(requires(Permission.VIEW_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> MedicationDetail:
    med = _get_med(db, access, med_id)
    events = db.scalars(
        select(InventoryEvent)
        .where(InventoryEvent.medication_id == med.id)
        .order_by(InventoryEvent.id.desc())
        .limit(30)
    ).all()
    return MedicationDetail(
        medication=med_out(med, local_today(access.patient)),
        inventory=[
            InventoryOut(
                id=e.id,
                kind=e.kind,
                quantity_delta=float(e.quantity_delta),
                quantity_after=float(e.quantity_after),
                note=e.note,
                actor_name=e.actor.full_name if e.actor else None,
                created_at=e.created_at,
            )
            for e in events
        ],
    )


@router.put("/medications/{med_id}", response_model=MedicationOut)
def update_medication(
    med_id: int,
    body: MedicationIn,
    access: PatientAccess = Depends(requires(Permission.MANAGE_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> MedicationOut:
    med = _get_med(db, access, med_id)
    if med.archived_at:
        raise AppError("This medicine has been removed and can no longer be edited.")
    now = utcnow()
    before_sig = _schedule_signature(med)
    fields = body.model_dump(exclude={"times"})
    before = {k: getattr(med, k) for k in fields}
    for key, value in fields.items():
        setattr(med, key, value)
    _set_times(med, body.times)
    db.flush()
    changes = audit.diff(before, fields)
    schedule_changed = _schedule_signature(med) != before_sig
    if schedule_changed:
        # Future unconfirmed doses are cancelled (kept, labelled) and regenerated from now.
        doses.cancel_future(db, med, now, "schedule_changed")
        med.schedule_anchor_at = now
        if med.status == MedicationStatus.ACTIVE:
            doses.materialize(db, now, [med.id])
        changes["times"] = [t.local_time.strftime("%H:%M") for t in med.times]
    if changes:
        audit.record(
            db,
            patient_id=access.patient.id,
            actor=access.user,
            action="medication.schedule_changed" if schedule_changed else "medication.updated",
            entity_type="medication",
            entity_id=med.id,
            summary=(
                f"{access.user.full_name} changed the schedule for {med.name}"
                if schedule_changed
                else f"{access.user.full_name} updated {med.name}"
            ),
            details={"changes": changes},
        )
    invalidate_refresh(access.patient.id)
    db.commit()
    return med_out(med, local_today(access.patient))


@router.post("/medications/{med_id}/status", response_model=MedicationOut)
def set_medication_status(
    med_id: int,
    body: StatusIn,
    access: PatientAccess = Depends(requires(Permission.MANAGE_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> MedicationOut:
    med = _get_med(db, access, med_id)
    if med.archived_at:
        raise AppError("This medicine has been removed.")
    if med.status == body.status:
        return med_out(med, local_today(access.patient))
    now = utcnow()
    previous = med.status
    med.status = body.status
    med.status_reason = body.reason.strip()
    if body.status == MedicationStatus.ACTIVE:
        med.schedule_anchor_at = now
        doses.materialize(db, now, [med.id])
    else:
        doses.cancel_future(db, med, now, body.status.value)
    verb = {"active": "resumed", "paused": "paused", "discontinued": "discontinued"}[body.status]
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action=f"medication.{verb}",
        entity_type="medication",
        entity_id=med.id,
        summary=f"{access.user.full_name} {verb} {med.name}"
        + (f": {med.status_reason}" if med.status_reason else ""),
        details={"from": previous, "to": body.status.value},
    )
    invalidate_refresh(access.patient.id)
    db.commit()
    return med_out(med, local_today(access.patient))


@router.delete("/medications/{med_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_medication(
    med_id: int,
    access: PatientAccess = Depends(requires(Permission.MANAGE_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> None:
    """Removes the medicine from lists while keeping its dose and stock history."""
    med = _get_med(db, access, med_id)
    if med.archived_at:
        return
    now = utcnow()
    doses.cancel_future(db, med, now, "removed")
    med.archived_at = now
    med.status = MedicationStatus.DISCONTINUED
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="medication.removed",
        entity_type="medication",
        entity_id=med.id,
        summary=f"{access.user.full_name} removed {med.name} (history kept)",
    )
    invalidate_refresh(access.patient.id)
    db.commit()


@router.post("/medications/{med_id}/inventory", response_model=MedicationDetail)
def record_inventory(
    med_id: int,
    body: InventoryIn,
    access: PatientAccess = Depends(requires(Permission.VIEW_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> MedicationDetail:
    # Refills can be recorded by anyone who confirms doses (e.g. a caregiver collecting a
    # prescription); correcting the count changes the record, so it needs management rights.
    if body.kind == "refill" and not (
        access.can(Permission.CONFIRM_DOSES) or access.can(Permission.MANAGE_MEDICATIONS)
    ):
        raise Forbidden("You don't have permission to record refills.")
    if body.kind == "correction":
        access.require(Permission.MANAGE_MEDICATIONS)
    med = _get_med(db, access, med_id)
    before = med.quantity_on_hand
    if body.kind == "refill":
        inventory.apply(
            db,
            med,
            InventoryKind.REFILL,
            delta=body.quantity,
            actor=access.user,
            note=body.note.strip(),
        )
        summary = (
            f"{access.user.full_name} recorded a refill of {float(body.quantity):g} for {med.name}"
        )
    else:
        inventory.apply(
            db,
            med,
            InventoryKind.CORRECTION,
            absolute=body.quantity,
            actor=access.user,
            note=body.note.strip(),
        )
        count = f"{float(body.quantity):g}"
        summary = f"{access.user.full_name} corrected the stock count for {med.name} to {count}"
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action=f"inventory.{body.kind}",
        entity_type="medication",
        entity_id=med.id,
        summary=summary,
        details={
            "before": str(before) if before is not None else None,
            "after": str(med.quantity_on_hand),
        },
    )
    db.commit()
    return get_medication(med_id, access, db)


@router.post(
    "/medications/{med_id}/as-needed", response_model=DoseOut, status_code=status.HTTP_201_CREATED
)
def record_as_needed(
    med_id: int,
    body: AsNeededIn,
    access: PatientAccess = Depends(requires(Permission.CONFIRM_DOSES)),
    db: Session = Depends(get_db),
) -> DoseOut:
    med = _get_med(db, access, med_id)
    dose = doses.record_as_needed(
        db, med, access.user, access.membership.role, utcnow(), body.amount
    )
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="dose.as_needed",
        entity_type="dose",
        entity_id=dose.id,
        summary=f"{access.user.full_name} recorded an as-needed dose of {med.name}",
    )
    invalidate_refresh(access.patient.id)
    db.commit()
    return dose_out(dose)


# ---- doses ----------------------------------------------------------------------------


# Last on-read refresh per patient (in app time). Reads within REFRESH_INTERVAL skip the
# refresh; any medicine change clears the entry. Per process, so serverless instances simply
# refresh a little more often; correctness never depends on it.
_last_refresh: dict[int, datetime] = {}
REFRESH_INTERVAL = timedelta(seconds=30)


def invalidate_refresh(patient_id: int) -> None:
    _last_refresh.pop(patient_id, None)


def refresh_patient_doses(db: Session, patient: Patient, now: datetime) -> None:
    """Brings this patient's doses up to date on read, so screens are correct even between
    scheduler ticks. Notifications are still sent only by the scheduler."""
    last = _last_refresh.get(patient.id)
    if last is not None and timedelta(0) <= now - last < REFRESH_INTERVAL:
        return
    _last_refresh[patient.id] = now
    med_ids = list(
        db.scalars(
            select(Medication.id).where(
                Medication.patient_id == patient.id, Medication.status == MedicationStatus.ACTIVE
            )
        )
    )
    if med_ids:
        doses.materialize(db, now, med_ids)
    for dose in db.scalars(
        select(DoseEvent).where(
            DoseEvent.patient_id == patient.id,
            DoseEvent.status.in_([DoseStatus.SCHEDULED, DoseStatus.UNCONFIRMED]),
            DoseEvent.scheduled_at <= now,
        )
    ):
        new = doses.due_transitions(dose, patient, now)
        if new:
            dose.status = new
            dose.status_changed_at = now
    db.commit()


@router.get("/doses", response_model=list[DoseOut])
def list_doses(
    start: date | None = None,
    end: date | None = None,
    status_filter: list[DoseStatus] | None = Query(default=None, alias="status"),
    access: PatientAccess = Depends(requires(Permission.VIEW_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> list[DoseOut]:
    today = local_today(access.patient)
    start = start or today
    end = end or start
    if end < start or (end - start).days > 92:
        raise AppError("Choose a date range of up to 92 days.")
    if end >= today - timedelta(days=1):
        refresh_patient_doses(db, access.patient, utcnow())
    stmt = (
        select(DoseEvent)
        .where(
            DoseEvent.patient_id == access.patient.id,
            DoseEvent.local_date >= start,
            DoseEvent.local_date <= end,
        )
        .order_by(DoseEvent.scheduled_at, DoseEvent.id)
    )
    if status_filter:
        stmt = stmt.where(DoseEvent.status.in_(status_filter))
    else:
        stmt = stmt.where(DoseEvent.status != DoseStatus.CANCELLED)
    return [dose_out(d) for d in db.scalars(stmt)]


def _get_dose(db: Session, access: PatientAccess, dose_id: int) -> DoseEvent:
    dose = db.get(DoseEvent, dose_id)
    if dose is None or dose.patient_id != access.patient.id:
        raise NotFound("That dose was not found.")
    refresh_patient_doses(db, access.patient, utcnow())
    return dose


def _dose_label(d: DoseEvent) -> str:
    return f"{d.medication.name} ({d.local_time.strftime('%H:%M')} dose)"


@router.post("/doses/{dose_id}/take", response_model=DoseOut)
def take_dose(
    dose_id: int,
    access: PatientAccess = Depends(requires(Permission.CONFIRM_DOSES)),
    db: Session = Depends(get_db),
) -> DoseOut:
    dose = _get_dose(db, access, dose_id)
    doses.mark_taken(db, dose, access.user, access.membership.role, utcnow())
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="dose.taken",
        entity_type="dose",
        entity_id=dose.id,
        summary=f"{access.user.full_name} confirmed {_dose_label(dose)} as taken",
        details={"source": dose.confirmation_source},
    )
    db.commit()
    return dose_out(dose)


@router.post("/doses/{dose_id}/skip", response_model=DoseOut)
def skip_dose(
    dose_id: int,
    body: SkipIn,
    access: PatientAccess = Depends(requires(Permission.CONFIRM_DOSES)),
    db: Session = Depends(get_db),
) -> DoseOut:
    dose = _get_dose(db, access, dose_id)
    doses.mark_skipped(db, dose, access.user, access.membership.role, utcnow(), body.reason)
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="dose.skipped",
        entity_type="dose",
        entity_id=dose.id,
        summary=f"{access.user.full_name} marked {_dose_label(dose)} as skipped"
        + (f": {dose.skip_reason}" if dose.skip_reason else ""),
    )
    db.commit()
    return dose_out(dose)


@router.post("/doses/{dose_id}/snooze", response_model=DoseOut)
def snooze_dose(
    dose_id: int,
    body: SnoozeIn,
    access: PatientAccess = Depends(requires(Permission.CONFIRM_DOSES)),
    db: Session = Depends(get_db),
) -> DoseOut:
    dose = _get_dose(db, access, dose_id)
    doses.snooze(dose, access.patient, body.minutes, utcnow())
    db.commit()
    return dose_out(dose)


@router.post("/doses/{dose_id}/undo", response_model=DoseOut)
def undo_dose(
    dose_id: int,
    access: PatientAccess = Depends(requires(Permission.CONFIRM_DOSES)),
    db: Session = Depends(get_db),
) -> DoseOut:
    dose = _get_dose(db, access, dose_id)
    previous = dose.status
    doses.undo(db, dose, access.user, access.is_elder, access.patient, utcnow())
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="dose.undone",
        entity_type="dose",
        entity_id=dose.id,
        summary=f"{access.user.full_name} undid the {previous} record for {_dose_label(dose)}",
    )
    db.commit()
    return dose_out(dose)
