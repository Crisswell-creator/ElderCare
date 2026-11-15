"""In-app notification centre (the same outbox rows that drive email)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import get_current_user
from app.domain import SEVERITY_BY_KIND, Severity
from app.errors import NotFound
from app.models import Notification, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    patient_id: int | None
    kind: str
    subject: str
    body: str
    link_path: str
    email_status: str
    severity: str
    last_error: str
    attempts: int
    created_at: datetime
    read: bool


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    unread: int
    next_before: int | None


@router.get("", response_model=NotificationPage)
def list_notifications(
    before: int | None = None,
    unread_only: bool = False,
    kind: str | None = Query(default=None, pattern=r"^[a-z_]+$"),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPage:
    stmt = select(Notification).where(Notification.recipient_user_id == user.id)
    if before:
        stmt = stmt.where(Notification.id < before)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if kind:
        stmt = stmt.where(Notification.kind == kind)
    rows = list(db.scalars(stmt.order_by(Notification.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    unread = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.recipient_user_id == user.id, Notification.read_at.is_(None))
        )
        or 0
    )
    return NotificationPage(
        items=[
            NotificationOut(
                id=n.id,
                patient_id=n.patient_id,
                kind=n.kind,
                subject=n.subject,
                body=n.body,
                link_path=n.link_path,
                email_status=n.status,
                severity=SEVERITY_BY_KIND.get(n.kind, Severity.INFO).value,
                last_error=n.last_error if n.status == "failed" else "",
                attempts=n.attempts,
                created_at=n.created_at,
                read=n.read_at is not None,
            )
            for n in rows
        ],
        unread=unread,
        next_before=rows[-1].id if more and rows else None,
    )


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    n = db.get(Notification, notification_id)
    if n is None or n.recipient_user_id != user.id:
        raise NotFound("Notification not found.")
    n.read_at = n.read_at or utcnow()
    db.commit()


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    db.execute(
        update(Notification)
        .where(Notification.recipient_user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
