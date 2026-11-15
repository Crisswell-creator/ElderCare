"""Doctor appointments and the questions to bring to them."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import PatientAccess, get_owned, requires
from app.domain import AppointmentStatus, Permission
from app.errors import AppError, Conflict, Forbidden
from app.models import Appointment, Patient, VisitQuestion
from app.services import audit

router = APIRouter(prefix="/api/patients/{patient_id}", tags=["appointments"])

REMINDER_CHOICES = {10080, 2880, 1440, 240, 120, 60}


class AppointmentIn(BaseModel):
    doctor_name: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    specialty: Annotated[str, Field(max_length=80)] = ""
    date: date
    time: time
    duration_minutes: int = Field(default=30, ge=5, le=480)
    location: Annotated[str, Field(max_length=300)] = ""
    purpose: Annotated[str, Field(max_length=300)] = ""
    notes: Annotated[str, Field(max_length=2000)] = ""
    reminder_offsets: list[int] = Field(default_factory=lambda: [1440, 120], max_length=4)

    @field_validator("reminder_offsets")
    @classmethod
    def _offsets(cls, v: list[int]) -> list[int]:
        if any(o not in REMINDER_CHOICES for o in v):
            raise ValueError("Unsupported reminder time")
        return sorted(set(v), reverse=True)


class AppointmentOut(BaseModel):
    id: int
    doctor_name: str
    specialty: str
    starts_at: datetime
    local_date: date
    local_time: str
    duration_minutes: int
    location: str
    purpose: str
    notes: str
    status: str
    reminder_offsets: list[int]


class CancelIn(BaseModel):
    reason: Annotated[str, Field(max_length=200)] = ""


class QuestionIn(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=500, pattern=r"\S")]


class QuestionOut(BaseModel):
    id: int
    text: str
    author_name: str | None
    created_at: datetime
    resolved: bool
    is_mine: bool


def appt_out(a: Appointment, tz: str) -> AppointmentOut:
    local = a.starts_at.astimezone(ZoneInfo(tz))
    return AppointmentOut(
        id=a.id,
        doctor_name=a.doctor_name,
        specialty=a.specialty,
        starts_at=a.starts_at,
        local_date=local.date(),
        local_time=local.strftime("%H:%M"),
        duration_minutes=a.duration_minutes,
        location=a.location,
        purpose=a.purpose,
        notes=a.notes,
        status=a.status,
        reminder_offsets=list(a.reminder_offsets or []),
    )


def _to_utc(patient: Patient, d: date, t: time) -> datetime:
    return datetime.combine(
        d, t.replace(second=0, microsecond=0), tzinfo=ZoneInfo(patient.timezone)
    ).astimezone(UTC)


def _get(db: Session, access: PatientAccess, appt_id: int) -> Appointment:
    return get_owned(db, Appointment, appt_id, access, "appointment")


@router.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    scope: Literal["upcoming", "past", "all"] = "upcoming",
    access: PatientAccess = Depends(requires(Permission.VIEW_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> list[AppointmentOut]:
    now = utcnow()
    stmt = select(Appointment).where(Appointment.patient_id == access.patient.id)
    if scope == "upcoming":
        stmt = stmt.where(
            Appointment.starts_at >= now - timedelta(hours=2),
            Appointment.status == AppointmentStatus.SCHEDULED,
        ).order_by(Appointment.starts_at)
    elif scope == "past":
        stmt = (
            stmt.where(
                (Appointment.starts_at < now - timedelta(hours=2))
                | (Appointment.status != AppointmentStatus.SCHEDULED)
            )
            .order_by(Appointment.starts_at.desc())
            .limit(100)
        )
    else:
        stmt = stmt.order_by(Appointment.starts_at.desc()).limit(200)
    return [appt_out(a, access.patient.timezone) for a in db.scalars(stmt)]


@router.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def create_appointment(
    body: AppointmentIn,
    access: PatientAccess = Depends(requires(Permission.MANAGE_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> AppointmentOut:
    starts = _to_utc(access.patient, body.date, body.time)
    if starts < utcnow():
        raise AppError(
            "An upcoming appointment can't be in the past.", fields={"date": "Choose a future date"}
        )
    a = Appointment(
        patient_id=access.patient.id,
        created_by_user_id=access.user.id,
        starts_at=starts,
        **body.model_dump(exclude={"date", "time"}),
    )
    db.add(a)
    db.flush()
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="appointment.created",
        entity_type="appointment",
        entity_id=a.id,
        summary=f"{access.user.full_name} added an appointment with {a.doctor_name} "
        f"on {body.date:%d %b %Y}",
    )
    db.commit()
    return appt_out(a, access.patient.timezone)


@router.put("/appointments/{appt_id}", response_model=AppointmentOut)
def update_appointment(
    appt_id: int,
    body: AppointmentIn,
    access: PatientAccess = Depends(requires(Permission.MANAGE_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> AppointmentOut:
    a = _get(db, access, appt_id)
    if a.status != AppointmentStatus.SCHEDULED:
        raise Conflict("Only scheduled appointments can be edited.")
    starts = _to_utc(access.patient, body.date, body.time)
    fields = {**body.model_dump(exclude={"date", "time"}), "starts_at": starts}
    before = {k: getattr(a, k) for k in fields}
    for key, value in fields.items():
        setattr(a, key, value)
    changes = audit.diff(before, fields)
    if changes:
        moved = "starts_at" in changes
        audit.record(
            db,
            patient_id=access.patient.id,
            actor=access.user,
            action="appointment.rescheduled" if moved else "appointment.updated",
            entity_type="appointment",
            entity_id=a.id,
            summary=(
                f"{access.user.full_name} moved the appointment with "
                f"{a.doctor_name} to {body.date:%d %b %Y} {body.time:%H:%M}"
                if moved
                else f"{access.user.full_name} updated the appointment with {a.doctor_name}"
            ),
            details={"changes": changes},
        )
    db.commit()
    return appt_out(a, access.patient.timezone)


@router.post("/appointments/{appt_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(
    appt_id: int,
    body: CancelIn,
    access: PatientAccess = Depends(requires(Permission.MANAGE_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> AppointmentOut:
    a = _get(db, access, appt_id)
    if a.status != AppointmentStatus.SCHEDULED:
        raise Conflict("This appointment is not scheduled.")
    a.status = AppointmentStatus.CANCELLED
    if body.reason.strip():
        a.notes = (a.notes + "\n" if a.notes else "") + f"Cancelled: {body.reason.strip()}"
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="appointment.cancelled",
        entity_type="appointment",
        entity_id=a.id,
        summary=f"{access.user.full_name} cancelled the appointment with {a.doctor_name}"
        + (f": {body.reason.strip()}" if body.reason.strip() else ""),
    )
    db.commit()
    return appt_out(a, access.patient.timezone)


@router.post("/appointments/{appt_id}/complete", response_model=AppointmentOut)
def complete_appointment(
    appt_id: int,
    access: PatientAccess = Depends(requires(Permission.MANAGE_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> AppointmentOut:
    a = _get(db, access, appt_id)
    if a.status != AppointmentStatus.SCHEDULED:
        raise Conflict("This appointment is not scheduled.")
    a.status = AppointmentStatus.COMPLETED
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="appointment.completed",
        entity_type="appointment",
        entity_id=a.id,
        summary=f"{access.user.full_name} marked the visit with {a.doctor_name} as attended",
    )
    db.commit()
    return appt_out(a, access.patient.timezone)


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get("/appointments/{appt_id}/calendar.ics")
def appointment_ics(
    appt_id: int,
    access: PatientAccess = Depends(requires(Permission.VIEW_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> Response:
    """Standard iCalendar file, so the visit can be added to Google Calendar or any other
    calendar app."""
    a = _get(db, access, appt_id)
    fmt = "%Y%m%dT%H%M%SZ"
    end = a.starts_at + timedelta(minutes=a.duration_minutes)
    body = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//ElderCare//Appointments//EN",
            "BEGIN:VEVENT",
            f"UID:appointment-{a.id}@eldercare",
            f"DTSTAMP:{utcnow():{fmt}}",
            f"DTSTART:{a.starts_at:{fmt}}",
            f"DTEND:{end:{fmt}}",
            f"SUMMARY:{_ics_escape('Appointment: ' + a.doctor_name)}",
            f"LOCATION:{_ics_escape(a.location)}",
            f"DESCRIPTION:{_ics_escape(a.purpose)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    return Response(
        body,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="appointment-{a.id}.ics"'},
    )


# ---- questions for the doctor -----------------------------------------------------------


def _q_out(q: VisitQuestion, access: PatientAccess) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        text=q.text,
        author_name=q.author.full_name if q.author else None,
        created_at=q.created_at,
        resolved=q.resolved_at is not None,
        is_mine=q.author_user_id == access.user.id,
    )


@router.get("/questions", response_model=list[QuestionOut])
def list_questions(
    access: PatientAccess = Depends(requires(Permission.VIEW_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> list[QuestionOut]:
    rows = db.scalars(
        select(VisitQuestion)
        .where(VisitQuestion.patient_id == access.patient.id)
        .order_by(VisitQuestion.resolved_at.is_not(None), VisitQuestion.created_at)
        .limit(100)
    )
    return [_q_out(q, access) for q in rows]


@router.post("/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
def add_question(
    body: QuestionIn,
    access: PatientAccess = Depends(requires(Permission.VIEW_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> QuestionOut:
    q = VisitQuestion(
        patient_id=access.patient.id, text=body.text.strip(), author_user_id=access.user.id
    )
    db.add(q)
    db.flush()
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="question.added",
        entity_type="question",
        entity_id=q.id,
        summary=f"{access.user.full_name} added a question for the doctor",
    )
    db.commit()
    return _q_out(q, access)


def _get_q(db: Session, access: PatientAccess, qid: int) -> VisitQuestion:
    q = get_owned(db, VisitQuestion, qid, access, "question")
    if not (access.is_elder or q.author_user_id == access.user.id):
        raise Forbidden("Only the author or the elder can change this question.")
    return q


@router.post("/questions/{qid}/resolve", response_model=QuestionOut)
def resolve_question(
    qid: int,
    access: PatientAccess = Depends(requires(Permission.VIEW_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> QuestionOut:
    q = _get_q(db, access, qid)
    q.resolved_at = None if q.resolved_at else utcnow()
    db.commit()
    return _q_out(q, access)


@router.delete("/questions/{qid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(
    qid: int,
    access: PatientAccess = Depends(requires(Permission.VIEW_APPOINTMENTS)),
    db: Session = Depends(get_db),
) -> None:
    q = _get_q(db, access, qid)
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="question.removed",
        entity_type="question",
        entity_id=q.id,
        summary=f"{access.user.full_name} removed a question for the doctor",
    )
    db.delete(q)
    db.commit()
