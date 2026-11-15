"""Read models: dashboards, adherence analytics, activity history and the visit summary."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.appointments import AppointmentOut, appt_out
from app.api.medications import DoseOut, dose_out, local_today, med_out, refresh_patient_doses
from app.db import get_db, utcnow
from app.deps import PatientAccess, get_current_user, patient_access, requires
from app.domain import (
    AppointmentStatus,
    DoseStatus,
    MedicationStatus,
    MembershipStatus,
    Permission,
    RequestStatus,
)
from app.errors import AppError
from app.models import (
    AccessRequest,
    Allergy,
    Appointment,
    AuditEvent,
    Doctor,
    DoseEvent,
    EmergencyContact,
    HistoryEntry,
    Medication,
    Membership,
    Notification,
    User,
    VisitQuestion,
)
from app.services import adherence, audit, visit_pdf

router = APIRouter(tags=["insights"])


class ActivityOut(BaseModel):
    id: int
    action: str
    summary: str
    actor_name: str | None
    actor_user_id: int | None
    created_at: datetime
    changes: dict[str, Any] | None = None


class ActivityPage(BaseModel):
    items: list[ActivityOut]
    next_before: int | None


class AdherenceOut(BaseModel):
    start: date
    end: date
    granularity: str
    totals: dict[str, Any]
    series: list[dict[str, Any]]
    by_medication: list[dict[str, Any]]
    by_time_of_day: list[dict[str, Any]]
    insights: list[dict[str, str]]
    rules: list[str]


RULES = [
    "Adherence = taken ÷ (taken + skipped + missed). Skipped doses count as not taken.",
    "Unconfirmed doses (no record after the grace period) are shown separately and are not "
    "counted as missed.",
    "Cancelled doses (schedule changed or medicine paused) and as-needed records are excluded.",
    f"Insights appear only when each compared group has at least {adherence.MIN_SAMPLE} "
    f"recorded doses and differs by {adherence.MIN_GAP:.0f}+ percentage points.",
]


def _activity_out(e: AuditEvent) -> ActivityOut:
    changes = e.details.get("changes") if isinstance(e.details, dict) else None
    return ActivityOut(
        id=e.id,
        action=e.action,
        summary=e.summary,
        actor_name=e.actor.full_name if e.actor else "ElderCare",
        actor_user_id=e.actor_user_id,
        created_at=e.created_at,
        changes=changes if isinstance(changes, dict) else None,
    )


@router.get("/api/patients/{patient_id}/adherence", response_model=AdherenceOut)
def adherence_report(
    start: date | None = None,
    end: date | None = None,
    granularity: Literal["day", "week", "month"] = "day",
    medication_id: int | None = None,
    access: PatientAccess = Depends(requires(Permission.VIEW_ADHERENCE)),
    db: Session = Depends(get_db),
) -> AdherenceOut:
    end = end or local_today(access.patient)
    start = start or end - timedelta(days=29)
    if end < start or (end - start).days > 366:
        raise AppError("Choose a date range of up to one year.")
    refresh_patient_doses(db, access.patient, utcnow())
    rep = adherence.build(db, access.patient.id, start, end, granularity, medication_id)
    return AdherenceOut(
        start=start,
        end=end,
        granularity=granularity,
        totals=rep.totals.as_dict(),
        series=[{"period": k.isoformat(), **c.as_dict()} for k, c in sorted(rep.series.items())],
        by_medication=sorted(
            (
                {"medication_id": mid, "name": rep.medication_names[mid], **c.as_dict()}
                for mid, c in rep.by_medication.items()
            ),
            key=lambda r: str(r["name"]),
        ),
        by_time_of_day=[
            {"bucket": key, "label": label, **rep.by_time_of_day[key].as_dict()}
            for key, label in adherence.BUCKETS
            if key in rep.by_time_of_day
        ],
        insights=adherence.insights(rep),
        rules=RULES,
    )


@router.get("/api/patients/{patient_id}/activity", response_model=ActivityPage)
def activity(
    before: int | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    category: str | None = Query(default=None, pattern=r"^[a-z_]+$"),
    actor_user_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    access: PatientAccess = Depends(requires(Permission.VIEW_ACTIVITY)),
    db: Session = Depends(get_db),
) -> ActivityPage:
    """Newest first, keyset-paginated by id; filters by person, kind and date range (dates
    are interpreted in the elder's time zone)."""
    stmt = select(AuditEvent).where(AuditEvent.patient_id == access.patient.id)
    if before:
        stmt = stmt.where(AuditEvent.id < before)
    if category:
        stmt = stmt.where(AuditEvent.action.like(f"{category}.%"))
    if actor_user_id is not None:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    tz = ZoneInfo(access.patient.timezone)
    if start:
        stmt = stmt.where(AuditEvent.created_at >= datetime.combine(start, datetime.min.time(), tz))
    if end:
        stmt = stmt.where(
            AuditEvent.created_at
            < datetime.combine(end + timedelta(days=1), datetime.min.time(), tz)
        )
    rows = list(db.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return ActivityPage(
        items=[_activity_out(e) for e in rows], next_before=rows[-1].id if more and rows else None
    )


class OverviewOut(BaseModel):
    patient_id: int
    patient_name: str
    preferred_name: str
    timezone: str
    local_date: date
    my_role: str
    my_permissions: list[str]
    is_representative: bool
    can_decide_access: bool
    today_doses: list[DoseOut] | None
    low_stock: list[dict[str, Any]] | None
    upcoming_appointments: list[AppointmentOut] | None
    adherence_7d: dict[str, Any] | None
    adherence_30d: dict[str, Any] | None
    recent_activity: list[ActivityOut] | None
    pending_requests: int
    unread_notifications: int
    emergency_contacts: list[dict[str, Any]]


@router.get("/api/patients/{patient_id}/overview", response_model=OverviewOut)
def overview(
    access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> OverviewOut:
    """Everything a dashboard needs in one request, trimmed to the caller's permissions."""
    patient = access.patient
    today = local_today(patient)
    now = utcnow()
    today_doses = low_stock = upcoming = a7 = a30 = recent = None
    if access.can(Permission.VIEW_MEDICATIONS):
        refresh_patient_doses(db, patient, now)
        today_doses = [
            dose_out(d)
            for d in db.scalars(
                select(DoseEvent)
                .where(
                    DoseEvent.patient_id == patient.id,
                    DoseEvent.local_date == today,
                    DoseEvent.status != DoseStatus.CANCELLED,
                )
                .order_by(DoseEvent.scheduled_at)
            )
        ]
        meds = db.scalars(
            select(Medication).where(
                Medication.patient_id == patient.id,
                Medication.status == MedicationStatus.ACTIVE,
                Medication.archived_at.is_(None),
            )
        ).all()
        low_stock = [
            {
                "id": o.id,
                "name": o.name,
                "strength": o.strength,
                "quantity_on_hand": o.quantity_on_hand,
                "days_remaining": o.days_remaining,
                "estimated_run_out": o.estimated_run_out,
            }
            for o in (med_out(m, today) for m in meds)
            if o.low_stock
        ]
    if access.can(Permission.VIEW_APPOINTMENTS):
        upcoming = [
            appt_out(a, patient.timezone)
            for a in db.scalars(
                select(Appointment)
                .where(
                    Appointment.patient_id == patient.id,
                    Appointment.status == AppointmentStatus.SCHEDULED,
                    Appointment.starts_at >= now - timedelta(hours=2),
                )
                .order_by(Appointment.starts_at)
                .limit(5)
            )
        ]
    if access.can(Permission.VIEW_ADHERENCE):
        # One query for 30 days; the 7-day figure is summed from the same daily series.
        rep30 = adherence.build(db, patient.id, today - timedelta(days=29), today, "day")
        a30 = rep30.totals.as_dict()
        a7 = adherence.totals_since(rep30, today - timedelta(days=6)).as_dict()
    if access.can(Permission.VIEW_ACTIVITY):
        recent = [
            _activity_out(e)
            for e in db.scalars(
                select(AuditEvent)
                .where(AuditEvent.patient_id == patient.id)
                .order_by(AuditEvent.id.desc())
                .limit(8)
            )
        ]
    pending = 0
    if access.can_decide_access:
        pending = (
            db.scalar(
                select(func.count())
                .select_from(AccessRequest)
                .where(
                    AccessRequest.patient_id == patient.id,
                    AccessRequest.status == RequestStatus.PENDING,
                )
            )
            or 0
        )
    unread = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.recipient_user_id == access.user.id,
                Notification.patient_id == patient.id,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )
    contacts = [
        {
            "name": c.name,
            "relationship_label": c.relationship_label,
            "phone": c.phone,
            "is_primary": c.is_primary,
            "priority": c.priority,
            "email": c.email,
        }
        for c in db.scalars(
            select(EmergencyContact)
            .where(EmergencyContact.patient_id == patient.id)
            .order_by(EmergencyContact.priority, EmergencyContact.is_primary.desc())
        )
    ]
    return OverviewOut(
        patient_id=patient.id,
        patient_name=patient.full_name,
        preferred_name=patient.preferred_name,
        timezone=patient.timezone,
        local_date=today,
        my_role=access.membership.role,
        my_permissions=sorted(access.permissions),
        is_representative=access.membership.is_representative,
        can_decide_access=access.can_decide_access,
        today_doses=today_doses,
        low_stock=low_stock,
        upcoming_appointments=upcoming,
        adherence_7d=a7,
        adherence_30d=a30,
        recent_activity=recent,
        pending_requests=pending,
        unread_notifications=unread,
        emergency_contacts=contacts,
    )


class CircleSummary(BaseModel):
    patient_id: int
    patient_name: str
    preferred_name: str
    role: str
    local_date: date
    doses_today: dict[str, int] | None
    needs_attention: int | None
    next_appointment: AppointmentOut | None
    pending_requests: int


@router.get("/api/me/overview", response_model=list[CircleSummary])
def my_overview(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[CircleSummary]:
    """Summary of every care circle the user belongs to, for the caregiver/family home.
    Uses a fixed number of grouped queries regardless of how many patients there are."""
    memberships = db.scalars(
        select(Membership).where(
            Membership.user_id == user.id, Membership.status == MembershipStatus.ACTIVE
        )
    ).all()
    if not memberships:
        return []
    now = utcnow()
    by_pid = {m.patient_id: m for m in memberships}
    local_dates = {
        pid: now.astimezone(ZoneInfo(m.patient.timezone)).date() for pid, m in by_pid.items()
    }

    def perm(m: Membership, p: Permission) -> bool:
        return m.role == "elder" or p in (m.permissions or [])

    for m in by_pid.values():
        if perm(m, Permission.VIEW_MEDICATIONS):
            refresh_patient_doses(db, m.patient, now)
    med_pids = [pid for pid, m in by_pid.items() if perm(m, Permission.VIEW_MEDICATIONS)]
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if med_pids:
        for pid, d, status, n in db.execute(
            select(DoseEvent.patient_id, DoseEvent.local_date, DoseEvent.status, func.count())
            .where(
                DoseEvent.patient_id.in_(med_pids),
                DoseEvent.local_date.in_(set(local_dates.values())),
                DoseEvent.status != DoseStatus.CANCELLED,
                DoseEvent.as_needed.is_(False),
            )
            .group_by(DoseEvent.patient_id, DoseEvent.local_date, DoseEvent.status)
        ):
            if d == local_dates[pid]:
                counts[pid][status] += n
    appt_pids = [pid for pid, m in by_pid.items() if perm(m, Permission.VIEW_APPOINTMENTS)]
    next_appt: dict[int, Appointment] = {}
    if appt_pids:
        for a in db.scalars(
            select(Appointment)
            .where(
                Appointment.patient_id.in_(appt_pids),
                Appointment.status == AppointmentStatus.SCHEDULED,
                Appointment.starts_at >= now,
            )
            .order_by(Appointment.starts_at)
        ):
            next_appt.setdefault(a.patient_id, a)
    decider_pids = [
        pid
        for pid, m in by_pid.items()
        if m.role == "elder" or (m.is_representative and perm(m, Permission.MANAGE_CARE_TEAM))
    ]
    pending: dict[int, int] = {}
    if decider_pids:
        pending = dict(
            db.execute(
                select(AccessRequest.patient_id, func.count())
                .where(
                    AccessRequest.patient_id.in_(decider_pids),
                    AccessRequest.status == RequestStatus.PENDING,
                )
                .group_by(AccessRequest.patient_id)
            ).all()
        )
    out = []
    for pid, m in by_pid.items():
        c = counts.get(pid) if pid in med_pids else None
        out.append(
            CircleSummary(
                patient_id=pid,
                patient_name=m.patient.full_name,
                preferred_name=m.patient.preferred_name,
                role=m.role,
                local_date=local_dates[pid],
                doses_today={
                    k: (c or {}).get(k, 0)
                    for k in ("scheduled", "taken", "skipped", "missed", "unconfirmed")
                }
                if pid in med_pids
                else None,
                needs_attention=(c.get("unconfirmed", 0) + c.get("missed", 0))
                if c
                else (0 if pid in med_pids else None),
                next_appointment=appt_out(next_appt[pid], m.patient.timezone)
                if pid in next_appt
                else None,
                pending_requests=pending.get(pid, 0),
            )
        )
    return sorted(out, key=lambda s: (-(s.needs_attention or 0), s.patient_name))


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _schedule_text(m: Medication) -> str:
    if m.schedule_type == "as_needed":
        return "As needed"
    parts = []
    for t in m.times:
        days = [DAY_NAMES[d] for d in range(7) if t.days_mask & (1 << d)]
        when = t.local_time.strftime("%H:%M")
        parts.append(when if len(days) == 7 else f"{when} ({', '.join(days)})")
    return ", ".join(parts)


@router.get("/api/patients/{patient_id}/visit-summary.pdf")
def visit_summary(
    access: PatientAccess = Depends(requires(Permission.VIEW_PROFILE, Permission.VIEW_MEDICATIONS)),
    db: Session = Depends(get_db),
) -> Response:
    patient = access.patient
    pid = patient.id
    today = local_today(patient)
    now = utcnow()
    meds = db.scalars(
        select(Medication)
        .where(
            Medication.patient_id == pid,
            Medication.status == MedicationStatus.ACTIVE,
            Medication.archived_at.is_(None),
        )
        .order_by(Medication.name)
    ).all()
    doctor = db.scalar(
        select(Doctor).where(Doctor.patient_id == pid).order_by(Doctor.is_primary.desc()).limit(1)
    )
    allergies = [
        f"{a.substance}"
        + (f" — {a.reaction}" if a.reaction else "")
        + (f" ({a.severity})" if a.severity != "unknown" else "")
        for a in db.scalars(select(Allergy).where(Allergy.patient_id == pid))
    ]
    history = [
        f"{h.title} ({h.kind}, {h.status})" + (f", {h.occurred_on:%b %Y}" if h.occurred_on else "")
        for h in db.scalars(
            select(HistoryEntry)
            .where(HistoryEntry.patient_id == pid)
            .order_by(HistoryEntry.status, HistoryEntry.occurred_on.desc())
        )
    ]
    rep = adherence.build(db, pid, today - timedelta(days=29), today, "day")
    t = rep.totals
    adherence_line = (
        f"{t.taken} taken, {t.skipped} skipped, {t.missed} missed, {t.unconfirmed} not "
        f"confirmed, out of {t.scheduled} scheduled doses"
        + (f" — {t.adherence:.0f}% of recorded doses taken." if t.adherence is not None else ".")
    )
    show_adherence = access.can(Permission.VIEW_ADHERENCE)
    can_appts = access.can(Permission.VIEW_APPOINTMENTS)
    appts = (
        [
            f"{appt_out(a, patient.timezone).local_date:%a %d %b %Y} "
            f"{appt_out(a, patient.timezone).local_time} — {a.doctor_name}"
            + (f" ({a.specialty})" if a.specialty else "")
            + (f": {a.purpose}" if a.purpose else "")
            for a in db.scalars(
                select(Appointment)
                .where(
                    Appointment.patient_id == pid,
                    Appointment.status == AppointmentStatus.SCHEDULED,
                    Appointment.starts_at >= now,
                )
                .order_by(Appointment.starts_at)
                .limit(5)
            )
        ]
        if can_appts
        else []
    )
    questions = (
        [
            q.text
            for q in db.scalars(
                select(VisitQuestion)
                .where(VisitQuestion.patient_id == pid, VisitQuestion.resolved_at.is_(None))
                .order_by(VisitQuestion.created_at)
            )
        ]
        if can_appts
        else []
    )
    pdf = visit_pdf.render(
        visit_pdf.VisitData(
            patient_name=patient.full_name,
            date_of_birth=patient.date_of_birth,
            phone=patient.phone,
            primary_doctor=(
                f"{doctor.name}"
                + (f", {doctor.clinic}" if doctor.clinic else "")
                + (f" ({doctor.phone})" if doctor.phone else "")
            )
            if doctor
            else "",
            allergies=allergies,
            history=history,
            medications=[
                visit_pdf.MedLine(
                    name=m.name,
                    strength=m.strength,
                    dose=f"{float(m.dose_amount):g} {m.dose_unit}",
                    schedule=_schedule_text(m),
                    instructions=m.instructions or "—",
                )
                for m in meds
            ],
            adherence_line=adherence_line
            if show_adherence
            else "Not included: the preparer cannot view adherence reports.",
            adherence_basis=(
                "Counted from doses recorded in ElderCare. Unconfirmed doses are not "
                "counted as missed; skipped doses count as not taken."
            )
            if show_adherence
            else "",
            appointments=appts,
            questions=questions,
            generated_at=now.astimezone(ZoneInfo(patient.timezone)),
            generated_by=access.user.full_name,
        )
    )
    audit.record(
        db,
        patient_id=pid,
        actor=access.user,
        action="visit_summary.generated",
        entity_type="patient",
        entity_id=pid,
        summary=f"{access.user.full_name} created a doctor visit summary",
    )
    db.commit()
    filename = f"visit-summary-{today:%Y-%m-%d}.pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )
