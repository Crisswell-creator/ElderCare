"""Notification outbox: queue (idempotently) and deliver with retries and backoff."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain import NotificationStatus
from app.logging_setup import log_event
from app.models import Notification, User
from app.services.email import EmailError, OutgoingEmail, render, send

logger = logging.getLogger("eldercare.notify")


def enqueue(
    db: Session,
    *,
    recipient: User,
    kind: str,
    dedupe_key: str,
    subject: str,
    paragraphs: list[str],
    link_path: str = "",
    patient_id: int | None = None,
    send_email: bool = True,
    now: datetime | None = None,
) -> bool:
    """Queues one notification. Returns False when the dedupe key already exists, so callers
    can run on every scheduler tick without producing duplicates."""
    if db.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key)):
        return False
    note = Notification(
        patient_id=patient_id,
        recipient_user_id=recipient.id,
        kind=kind,
        dedupe_key=dedupe_key,
        subject=subject,
        body="\n\n".join(paragraphs),
        link_path=link_path,
        status=NotificationStatus.PENDING if send_email else NotificationStatus.SUPPRESSED,
    )
    if now is not None:
        note.created_at = now
        note.next_attempt_at = now
    try:
        with db.begin_nested():  # a concurrent tick may insert the same key first
            db.add(note)
    except IntegrityError:
        return False
    return True


def _backoff(attempts: int) -> timedelta:
    return timedelta(minutes=min(2**attempts, 60))


def deliver_pending(db: Session, now: datetime, limit: int = 50) -> dict[str, int]:
    settings = get_settings()
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.status == NotificationStatus.PENDING,
            Notification.next_attempt_at <= now,
        )
        .order_by(Notification.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True, of=Notification)  # lock only outbox rows
    ).all()
    stats = {"sent": 0, "retrying": 0, "failed": 0}
    for note in rows:
        link = f"{settings.app_base_url}{note.link_path}" if note.link_path else ""
        text, page = render(
            heading=note.subject,
            paragraphs=note.body.split("\n\n"),
            action_label="Open ElderCare" if link else "",
            action_url=link,
        )
        note.attempts += 1
        try:
            send(OutgoingEmail(to=note.recipient.email, subject=note.subject, text=text, html=page))
            note.status = NotificationStatus.SENT
            note.sent_at = now
            note.last_error = ""
            stats["sent"] += 1
        except EmailError as exc:
            note.last_error = str(exc)[:500]
            if note.attempts >= settings.email_max_attempts:
                note.status = NotificationStatus.FAILED
                stats["failed"] += 1
                log_event(
                    logger,
                    logging.ERROR,
                    "notification permanently failed",
                    notification_id=note.id,
                    attempts=note.attempts,
                    error=note.last_error,
                )
            else:
                note.next_attempt_at = now + _backoff(note.attempts)
                stats["retrying"] += 1
                log_event(
                    logger,
                    logging.WARNING,
                    "notification delivery failed, will retry",
                    notification_id=note.id,
                    attempts=note.attempts,
                )
    # One commit for the batch: row locks are held until here, so a parallel tick cannot
    # pick up the same rows. A crash mid-batch means at-least-once delivery, never zero.
    db.commit()
    return stats
