"""Reports and exports computed from stored records. Each export requires the permission for
the data it contains and is written to the activity history."""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.medications import local_today
from app.db import get_db, utcnow
from app.deps import PatientAccess, patient_access, requires
from app.domain import Permission
from app.errors import AppError
from app.models import Appointment, AuditEvent, CareTask, DoseEvent, InventoryEvent, Medication
from app.services import adherence, audit

router = APIRouter(prefix="/api/patients/{patient_id}/reports", tags=["reports"])


class ReportOut(BaseModel):
    start: date
    end: date
    adherence: dict[str, Any] | None
    appointments: dict[str, Any] | None
    tasks: dict[str, Any]
    refills: list[dict[str, Any]] | None
    activity_by_person: list[dict[str, Any]] | None
    notes: list[str]


def _range(access: PatientAccess, start: date | None, end: date | None) -> tuple[date, date]:
    end = end or local_today(access.patient)
    start = start or end - timedelta(days=29)
    if end < start or (end - start).days > 366:
        raise AppError("Choose a date range of up to one year.")
    return start, end


def _bounds(access: PatientAccess, start: date, end: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(access.patient.timezone)
    return (
        datetime.combine(start, datetime.min.time(), tz),
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tz),
    )


@router.get("", response_model=ReportOut)
def summary(
    start: date | None = None,
    end: date | None = None,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> ReportOut:
    start, end = _range(access, start, end)
    lo, hi = _bounds(access, start, end)
    pid = access.patient.id
    now = utcnow()
    adh = appts = refills = by_person = None
    if access.can(Permission.VIEW_ADHERENCE):
        rep = adherence.build(db, pid, start, end, "week")
        adh = {
            "totals": rep.totals.as_dict(),
            "weekly": [
                {"period": k.isoformat(), **c.as_dict()} for k, c in sorted(rep.series.items())
            ],
        }
    if access.can(Permission.VIEW_APPOINTMENTS):
        rows = db.scalars(
            select(Appointment).where(
                Appointment.patient_id == pid,
                Appointment.starts_at >= lo,
                Appointment.starts_at < hi,
            )
        ).all()
        c = Counter(a.status for a in rows)
        appts = {
            "total": len(rows),
            "completed": c["completed"],
            "cancelled": c["cancelled"],
            "upcoming": sum(1 for a in rows if a.status == "scheduled" and a.starts_at >= now),
            # A past visit still "scheduled" was never marked attended or cancelled; it
            # is reported as unrecorded rather than assumed missed.
            "past_unrecorded": sum(
                1 for a in rows if a.status == "scheduled" and a.starts_at < now
            ),
        }
    tasks = db.scalars(select(CareTask).where(CareTask.patient_id == pid)).all()
    today = local_today(access.patient)
    per: dict[str, Counter[str]] = defaultdict(Counter)
    for t in tasks:
        who = t.assignee.full_name if t.assignee else "Unassigned"
        if t.status in ("open", "in_progress"):
            per[who]["open"] += 1
            if t.due_date and t.due_date < today:
                per[who]["overdue"] += 1
        elif t.status == "done" and t.completed_at and lo <= t.completed_at < hi:
            per[who]["completed_in_period"] += 1
    task_summary = {
        "open": sum(c["open"] for c in per.values()),
        "overdue": sum(c["overdue"] for c in per.values()),
        "completed_in_period": sum(c["completed_in_period"] for c in per.values()),
        "by_person": [{"name": k, **dict(v)} for k, v in sorted(per.items())],
    }
    if access.can(Permission.VIEW_MEDICATIONS):
        ev = db.execute(
            select(InventoryEvent, Medication.name)
            .join(Medication, Medication.id == InventoryEvent.medication_id)
            .where(
                Medication.patient_id == pid,
                InventoryEvent.kind == "refill",
                InventoryEvent.created_at >= lo,
                InventoryEvent.created_at < hi,
            )
            .order_by(InventoryEvent.created_at)
        ).all()
        refills = [
            {
                "medication": n,
                "quantity": float(e.quantity_delta),
                "recorded_at": e.created_at.isoformat(),
                "by": e.actor.full_name if e.actor else None,
            }
            for e, n in ev
        ]
    if access.can(Permission.VIEW_ACTIVITY):
        counts = Counter(
            (e.actor.full_name if e.actor else "ElderCare")
            for e in db.scalars(
                select(AuditEvent).where(
                    AuditEvent.patient_id == pid,
                    AuditEvent.created_at >= lo,
                    AuditEvent.created_at < hi,
                )
            )
        )
        # Shown alphabetically, not ranked: this is a record of contributions, not a contest.
        by_person = [{"name": k, "actions": v} for k, v in sorted(counts.items())]
    return ReportOut(
        start=start,
        end=end,
        adherence=adh,
        appointments=appts,
        tasks=task_summary,
        refills=refills,
        activity_by_person=by_person,
        notes=[
            "Unconfirmed doses are not counted as missed.",
            "Past appointments never marked attended or cancelled are shown "
            "as unrecorded, not missed.",
        ],
    )


FORMULA_PREFIXES = ("=", "+", "-", "@", chr(9), chr(13))  # OWASP CSV injection list


def _csv(rows: list[list[Any]], header: list[str], name: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        # Neutralise spreadsheet formula injection in user-entered text.
        w.writerow([f"'{v}" if isinstance(v, str) and v[:1] in FORMULA_PREFIXES else v for v in r])
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
        },
    )


def _log_export(db: Session, access: PatientAccess, kind: str, start: date, end: date) -> None:
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="export.created",
        entity_type="patient",
        entity_id=access.patient.id,
        summary=f"{access.user.full_name} exported {kind} ({start:%d %b} to {end:%d %b %Y})",
    )
    db.commit()


@router.get("/doses.csv")
def doses_csv(
    start: date | None = None,
    end: date | None = None,
    access: PatientAccess = Depends(requires(Permission.VIEW_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> Response:
    start, end = _range(access, start, end)
    rows = db.scalars(
        select(DoseEvent)
        .where(
            DoseEvent.patient_id == access.patient.id,
            DoseEvent.local_date >= start,
            DoseEvent.local_date <= end,
        )
        .order_by(DoseEvent.scheduled_at)
    ).all()
    _log_export(db, access, "dose records", start, end)
    return _csv(
        [
            [
                d.local_date.isoformat(),
                d.local_time.strftime("%H:%M"),
                d.medication.name,
                d.medication.strength,
                f"{float(d.dose_amount):g}",
                d.status,
                "yes" if d.as_needed else "no",
                d.confirmed_by.full_name if d.confirmed_by else "",
                d.confirmation_source,
                d.confirmed_at.isoformat() if d.confirmed_at else "",
                d.skip_reason,
            ]
            for d in rows
        ],
        [
            "date",
            "time",
            "medicine",
            "strength",
            "amount",
            "status",
            "as_needed",
            "recorded_by",
            "recorded_as",
            "recorded_at_utc",
            "skip_reason",
        ],
        f"doses-{start}-{end}.csv",
    )


@router.get("/appointments.csv")
def appointments_csv(
    start: date | None = None,
    end: date | None = None,
    access: PatientAccess = Depends(requires(Permission.VIEW_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> Response:
    if end is None:  # upcoming visits are the useful part of an appointment export
        end = local_today(access.patient) + timedelta(days=330)
        start = start or end - timedelta(days=360)  # stays within the one-year limit
    start, end = _range(access, start, end)
    lo, hi = _bounds(access, start, end)
    tz = ZoneInfo(access.patient.timezone)
    rows = db.scalars(
        select(Appointment)
        .where(
            Appointment.patient_id == access.patient.id,
            Appointment.starts_at >= lo,
            Appointment.starts_at < hi,
        )
        .order_by(Appointment.starts_at)
    ).all()
    _log_export(db, access, "appointments", start, end)
    return _csv(
        [
            [
                a.starts_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                a.doctor_name,
                a.specialty,
                a.location,
                a.purpose,
                a.status,
            ]
            for a in rows
        ],
        ["local_time", "doctor", "specialty", "location", "purpose", "status"],
        f"appointments-{start}-{end}.csv",
    )


@router.get("/tasks.csv")
def tasks_csv(
    access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> Response:
    rows = db.scalars(
        select(CareTask)
        .where(CareTask.patient_id == access.patient.id)
        .order_by(CareTask.created_at)
    ).all()
    today = local_today(access.patient)
    _log_export(db, access, "care tasks", today, today)
    return _csv(
        [
            [
                t.title,
                t.priority,
                t.status,
                t.due_date.isoformat() if t.due_date else "",
                t.assignee.full_name if t.assignee else "",
                t.created_by.full_name if t.created_by else "",
                t.completed_at.isoformat() if t.completed_at else "",
                t.completion_note,
            ]
            for t in rows
        ],
        [
            "title",
            "priority",
            "status",
            "due",
            "assigned_to",
            "created_by",
            "completed_at_utc",
            "completion_note",
        ],
        "care-tasks.csv",
    )
