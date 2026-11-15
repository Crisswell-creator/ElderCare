"""Care coordination: tasks, shared notes, and the elder's "ask my care circle for help"
alert. All of it is scoped to one care circle and follows that circle's permissions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import PatientAccess, get_owned, patient_access
from app.domain import MembershipStatus, NotificationKind, Permission
from app.errors import AppError, Forbidden, NotFound, TooManyRequests
from app.models import Appointment, CareNote, CareTask, Membership, Notification
from app.services import audit, notify

router = APIRouter(prefix="/api/patients/{patient_id}", tags=["collaboration"])

TaskStatus = Literal["open", "in_progress", "done", "cancelled"]
NoteKind = Literal["note", "care_instruction", "appointment_prep", "update"]
NOTE_LABEL = {
    "note": "note",
    "care_instruction": "care instruction",
    "appointment_prep": "appointment preparation note",
    "update": "update",
}


# ---- tasks ------------------------------------------------------------------------------


class TaskIn(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=160, pattern=r"\S")]
    description: Annotated[str, Field(max_length=2000)] = ""
    priority: Literal["low", "normal", "high"] = "normal"
    due_date: date | None = None
    assignee_user_id: int | None = None


class TaskStatusIn(BaseModel):
    status: TaskStatus
    note: Annotated[str, Field(max_length=1000)] = ""


class TaskOut(BaseModel):
    id: int
    title: str
    description: str
    priority: str
    status: str
    due_date: date | None
    overdue: bool
    assignee_user_id: int | None
    assignee_name: str | None
    created_by_name: str | None
    completion_note: str
    completed_at: datetime | None
    created_at: datetime
    can_edit: bool
    can_update_status: bool


def _can_manage_tasks(access: PatientAccess) -> bool:
    return access.can(Permission.MANAGE_TASKS) or access.can_decide_access


def _task_out(t: CareTask, access: PatientAccess, today: date) -> TaskOut:
    manage = _can_manage_tasks(access)
    mine = t.assignee_user_id == access.user.id
    return TaskOut(
        id=t.id,
        title=t.title,
        description=t.description,
        priority=t.priority,
        status=t.status,
        due_date=t.due_date,
        overdue=t.status in ("open", "in_progress")
        and t.due_date is not None
        and t.due_date < today,
        assignee_user_id=t.assignee_user_id,
        assignee_name=t.assignee.full_name if t.assignee else None,
        created_by_name=t.created_by.full_name if t.created_by else None,
        completion_note=t.completion_note,
        completed_at=t.completed_at,
        created_at=t.created_at,
        can_edit=manage or t.created_by_user_id == access.user.id,
        can_update_status=manage or mine or t.created_by_user_id == access.user.id,
    )


def _today(access: PatientAccess) -> date:
    return utcnow().astimezone(ZoneInfo(access.patient.timezone)).date()


def _check_assignee(db: Session, access: PatientAccess, user_id: int | None) -> None:
    if user_id is None:
        return
    ok = db.scalar(
        select(Membership.id).where(
            Membership.patient_id == access.patient.id,
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    if ok is None:
        raise AppError(
            "Tasks can only be assigned to people in this care circle.",
            fields={"assignee_user_id": "Not a member of this care circle"},
        )


def _get_task(db: Session, access: PatientAccess, task_id: int) -> CareTask:
    return get_owned(db, CareTask, task_id, access, "task")


def _notify_assignee(db: Session, access: PatientAccess, t: CareTask) -> None:
    if t.assignee is None or t.assignee_user_id == access.user.id:
        return
    notify.enqueue(
        db,
        recipient=t.assignee,
        kind=NotificationKind.TASK_ASSIGNED,
        dedupe_key=f"task:{t.id}:assigned:{t.assignee_user_id}:{utcnow().isoformat()}",
        subject="A care task was assigned to you",
        paragraphs=[
            f"{access.user.full_name} assigned you a task in a care circle you help with.",
            "Open ElderCare to see the details and due date.",
        ],
        link_path=f"/p/{access.patient.id}/tasks",
        patient_id=access.patient.id,
        send_email=t.assignee.email_verified_at is not None,
    )


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    scope: Literal["open", "mine", "done", "all"] = "open",
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    stmt = select(CareTask).where(CareTask.patient_id == access.patient.id)
    if scope == "open":
        stmt = stmt.where(CareTask.status.in_(["open", "in_progress"]))
    elif scope == "mine":
        stmt = stmt.where(
            CareTask.assignee_user_id == access.user.id,
            CareTask.status.in_(["open", "in_progress"]),
        )
    elif scope == "done":
        stmt = stmt.where(CareTask.status.in_(["done", "cancelled"]))
    rows = db.scalars(
        stmt.order_by(CareTask.due_date.is_(None), CareTask.due_date, CareTask.id.desc()).limit(200)
    )
    today = _today(access)
    return [_task_out(t, access, today) for t in rows]


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskIn, access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> TaskOut:
    if not _can_manage_tasks(access):
        raise Forbidden("You don't have permission to create tasks for this person.")
    _check_assignee(db, access, body.assignee_user_id)
    t = CareTask(
        patient_id=access.patient.id, created_by_user_id=access.user.id, **body.model_dump()
    )
    db.add(t)
    db.flush()
    db.refresh(t)
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="task.created",
        entity_type="task",
        entity_id=t.id,
        summary=f"{access.user.full_name} created the task “{t.title}”"
        + (f" for {t.assignee.full_name}" if t.assignee else ""),
    )
    _notify_assignee(db, access, t)
    db.commit()
    return _task_out(t, access, _today(access))


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    body: TaskIn,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> TaskOut:
    t = _get_task(db, access, task_id)
    if not (_can_manage_tasks(access) or t.created_by_user_id == access.user.id):
        raise Forbidden("You can't edit this task.")
    _check_assignee(db, access, body.assignee_user_id)
    before = {k: getattr(t, k) for k in body.model_dump()}
    reassigned = body.assignee_user_id != t.assignee_user_id
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.flush()
    db.refresh(t)
    changes = audit.diff(before, body.model_dump())
    if changes:
        audit.record(
            db,
            patient_id=access.patient.id,
            actor=access.user,
            action="task.reassigned" if reassigned else "task.updated",
            entity_type="task",
            entity_id=t.id,
            summary=(
                f"{access.user.full_name} reassigned “{t.title}” to "
                f"{t.assignee.full_name if t.assignee else 'nobody'}"
                if reassigned
                else f"{access.user.full_name} updated the task “{t.title}”"
            ),
            details={"changes": changes},
        )
    if reassigned:
        _notify_assignee(db, access, t)
    db.commit()
    return _task_out(t, access, _today(access))


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
def set_task_status(
    task_id: int,
    body: TaskStatusIn,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> TaskOut:
    t = _get_task(db, access, task_id)
    allowed = _can_manage_tasks(access) or access.user.id in (
        t.assignee_user_id,
        t.created_by_user_id,
    )
    if not allowed:
        raise Forbidden(
            "Only the assignee, the task's creator, or someone who manages tasks "
            "can change this task."
        )
    previous = t.status
    t.status = body.status
    t.completed_at = utcnow() if body.status == "done" else None
    if body.note.strip():
        t.completion_note = body.note.strip()
    verb = {
        "done": "completed",
        "cancelled": "cancelled",
        "in_progress": "started",
        "open": "reopened",
    }[body.status]
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action=f"task.{verb}",
        entity_type="task",
        entity_id=t.id,
        summary=f"{access.user.full_name} {verb} the task “{t.title}”"
        + (f": {t.completion_note}" if body.note.strip() else ""),
        details={"changes": {"status": [previous, body.status]}},
    )
    db.commit()
    return _task_out(t, access, _today(access))


# ---- shared notes -------------------------------------------------------------------------


class NoteIn(BaseModel):
    kind: NoteKind = "note"
    title: Annotated[str, Field(min_length=1, max_length=160, pattern=r"\S")]
    body: Annotated[str, Field(min_length=1, max_length=5000)]
    pinned: bool = False
    appointment_id: int | None = None


class NoteOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    pinned: bool
    appointment_id: int | None
    author_name: str | None
    created_at: datetime
    updated_at: datetime
    can_edit: bool


def _note_perm(kind: str) -> Permission:
    # Appointment preparation follows appointment visibility; everything else is part of the
    # health profile.
    return Permission.VIEW_APPOINTMENTS if kind == "appointment_prep" else Permission.VIEW_PROFILE


def _check_appointment(db: Session, access: PatientAccess, appointment_id: int | None) -> None:
    if appointment_id is None:
        return
    a = db.get(Appointment, appointment_id)
    if a is None or a.patient_id != access.patient.id:
        raise AppError("That appointment was not found.", fields={"appointment_id": "Not found"})


def _note_out(n: CareNote, access: PatientAccess) -> NoteOut:
    return NoteOut(
        id=n.id,
        kind=n.kind,
        title=n.title,
        body=n.body,
        pinned=n.pinned,
        appointment_id=n.appointment_id,
        author_name=n.author.full_name if n.author else None,
        created_at=n.created_at,
        updated_at=n.updated_at,
        can_edit=access.is_elder or n.author_user_id == access.user.id,
    )


@router.get("/notes", response_model=list[NoteOut])
def list_notes(
    kind: NoteKind | None = None,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> list[NoteOut]:
    kinds = [k for k in NOTE_LABEL if access.can(_note_perm(k))]
    if kind:
        if kind not in kinds:
            raise Forbidden("You don't have permission to see these notes.")
        kinds = [kind]
    if not kinds:
        return []
    rows = db.scalars(
        select(CareNote)
        .where(CareNote.patient_id == access.patient.id, CareNote.kind.in_(kinds))
        .order_by(CareNote.pinned.desc(), CareNote.created_at.desc())
        .limit(200)
    )
    return [_note_out(n, access) for n in rows]


@router.post("/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(
    body: NoteIn, access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> NoteOut:
    access.require(_note_perm(body.kind))
    _check_appointment(db, access, body.appointment_id)
    n = CareNote(patient_id=access.patient.id, author_user_id=access.user.id, **body.model_dump())
    db.add(n)
    db.flush()
    db.refresh(n)
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="note.created",
        entity_type="note",
        entity_id=n.id,
        summary=f"{access.user.full_name} added a {NOTE_LABEL[n.kind]}",
    )
    db.commit()
    return _note_out(n, access)


def _get_note(db: Session, access: PatientAccess, note_id: int) -> CareNote:
    n = get_owned(db, CareNote, note_id, access, "note")
    if not access.can(_note_perm(n.kind)):
        raise NotFound("That note was not found.")
    if not (access.is_elder or n.author_user_id == access.user.id):
        raise Forbidden("Only the author or the elder can change this note.")
    return n


@router.put("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    body: NoteIn,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> NoteOut:
    n = _get_note(db, access, note_id)
    access.require(_note_perm(body.kind))
    _check_appointment(db, access, body.appointment_id)
    before = {k: getattr(n, k) for k in ("title", "body", "kind", "pinned")}
    for k, v in body.model_dump().items():
        setattr(n, k, v)
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="note.updated",
        entity_type="note",
        entity_id=n.id,
        summary=f"{access.user.full_name} edited a {NOTE_LABEL[n.kind]}",
        # Field names only: note text must not reach people who can see activity
        # but not the note itself.
        details={"changed_fields": sorted(audit.diff(before, {k: getattr(n, k) for k in before}))},
    )
    db.commit()
    return _note_out(n, access)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: int, access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> None:
    n = _get_note(db, access, note_id)
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="note.removed",
        entity_type="note",
        entity_id=n.id,
        summary=f"{access.user.full_name} removed a {NOTE_LABEL[n.kind]}",
    )
    db.delete(n)
    db.commit()


# ---- help alert -----------------------------------------------------------------------------


class HelpIn(BaseModel):
    message: Annotated[str, Field(max_length=300)] = ""


class HelpOut(BaseModel):
    recipients: int
    emailed: int
    in_app_only: int
    created_at: datetime


class HelpStatusOut(BaseModel):
    created_at: datetime | None
    recipients: int
    email_sent: int
    email_pending: int
    email_failed: int
    in_app_only: int
    read: int


HELP_WINDOW = timedelta(minutes=10)


def _count(batch: list[Notification], status: str) -> int:
    return sum(1 for n in batch if n.status == status)


@router.post("/help-alerts", response_model=HelpOut, status_code=status.HTTP_201_CREATED)
def send_help_alert(
    body: HelpIn, access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> HelpOut:
    """The elder (or their representative) asks the care circle to get in touch. This is a
    notification to people the elder chose, not an emergency service, and says so."""
    if not (access.is_elder or access.membership.is_representative):
        raise Forbidden("Only the elder or their representative can send a help request.")
    now = utcnow()
    recent = db.scalar(
        select(Notification.id)
        .where(
            Notification.patient_id == access.patient.id,
            Notification.kind == "help_request",
            Notification.created_at >= now - HELP_WINDOW,
        )
        .limit(1)
    )
    if recent is not None:
        raise TooManyRequests("Your care circle was already alerted in the last 10 minutes.")
    members = db.scalars(
        select(Membership).where(
            Membership.patient_id == access.patient.id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.user_id != access.user.id,
        )
    ).all()
    name = access.patient.first_name
    emailed = 0
    stamp = now.isoformat()
    for m in members:
        verified = m.user.email_verified_at is not None
        notify.enqueue(
            db,
            recipient=m.user,
            kind=NotificationKind.HELP_REQUEST,
            dedupe_key=f"help:{access.patient.id}:{stamp}:{m.user_id}",
            subject=f"{name} asked for help in ElderCare",
            paragraphs=[
                f"{name} pressed “Ask my care circle for help” in ElderCare."
                + (f" Message: “{body.message.strip()}”" if body.message.strip() else ""),
                "Please contact them now. ElderCare has not contacted emergency "
                "services. If you believe it is an emergency, call your local "
                "emergency number.",
            ],
            link_path=f"/p/{access.patient.id}/emergency",
            patient_id=access.patient.id,
            send_email=verified,
            now=now,
        )
        emailed += int(verified)
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="help.requested",
        entity_type="patient",
        entity_id=access.patient.id,
        summary=f"{access.user.full_name} asked the care circle for help "
        f"({len(members)} people notified)",
    )
    db.commit()
    if not members:
        raise AppError(
            "There is nobody else in your care circle to alert yet. "
            "Call one of your emergency contacts instead."
        )
    return HelpOut(
        recipients=len(members), emailed=emailed, in_app_only=len(members) - emailed, created_at=now
    )


@router.get("/help-alerts/latest", response_model=HelpStatusOut)
def help_alert_status(
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
    since_minutes: int = Query(default=60, ge=1, le=1440),
) -> HelpStatusOut:
    """Delivery status as actually recorded, so the UI never claims more than happened.
    Limited to the elder and representatives: whether the elder asked for help is private."""
    if not (access.is_elder or access.membership.is_representative):
        raise Forbidden("Only the elder or their representative can see this.")
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.patient_id == access.patient.id,
            Notification.kind == "help_request",
            Notification.created_at >= utcnow() - timedelta(minutes=since_minutes),
        )
        .order_by(Notification.created_at.desc())
    ).all()
    if not rows:
        return HelpStatusOut(
            created_at=None,
            recipients=0,
            email_sent=0,
            email_pending=0,
            email_failed=0,
            in_app_only=0,
            read=0,
        )
    latest = rows[0].created_at
    batch = [n for n in rows if n.created_at == latest]
    return HelpStatusOut(
        created_at=latest,
        recipients=len(batch),
        email_sent=_count(batch, "sent"),
        email_pending=_count(batch, "pending"),
        email_failed=_count(batch, "failed"),
        in_app_only=_count(batch, "suppressed"),
        read=sum(1 for n in batch if n.read_at is not None),
    )
