"""The dose timeline: listing a date range and confirming, skipping, snoozing or undoing
a single dose. Each confirmation is audited with who acted and from where."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import PatientAccess, get_owned, requires
from app.domain import DoseStatus, Permission
from app.errors import AppError
from app.models import DoseEvent, Patient
from app.services import audit, doses

router = APIRouter(prefix="/api/patients/{patient_id}", tags=["doses"])


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
        doses.refresh_patient_doses(db, access.patient, utcnow())
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
    dose = get_owned(db, DoseEvent, dose_id, access, "dose")
    doses.refresh_patient_doses(db, access.patient, utcnow())
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
