"""Database-backed attempt throttling. Stored in the database rather than process memory so
the limit holds across Cloud Run instances and restarts."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.errors import TooManyRequests
from app.models import AuthAttempt


def ensure_allowed(db: Session, key: str, *, max_failures: int, window_minutes: int) -> None:
    since = utcnow() - timedelta(minutes=window_minutes)
    failures = db.scalar(
        select(func.count())
        .select_from(AuthAttempt)
        .where(AuthAttempt.key == key, AuthAttempt.created_at >= since, ~AuthAttempt.succeeded)
    )
    if (failures or 0) >= max_failures:
        raise TooManyRequests(
            f"Too many attempts. Please wait {window_minutes} minutes and try again."
        )


def ensure_quota(db: Session, key: str, *, limit: int, window_minutes: int) -> None:
    """Counts every use (not only failures), for usage quotas such as AI requests."""
    since = utcnow() - timedelta(minutes=window_minutes)
    used = db.scalar(
        select(func.count())
        .select_from(AuthAttempt)
        .where(AuthAttempt.key == key, AuthAttempt.created_at >= since)
    )
    if (used or 0) >= limit:
        raise TooManyRequests(
            f"You've reached the limit of {limit} questions in {window_minutes} minutes. "
            "Please try again shortly."
        )
    db.add(AuthAttempt(key=key, succeeded=True))
    db.commit()


def note_attempt(db: Session, key: str, *, succeeded: bool) -> None:
    if succeeded:
        # A success clears the failure streak for this key.
        db.execute(delete(AuthAttempt).where(AuthAttempt.key == key))
    db.add(AuthAttempt(key=key, succeeded=succeeded))
    db.commit()


def purge_older_than(db: Session, days: int) -> int:
    result = db.execute(
        delete(AuthAttempt).where(AuthAttempt.created_at < utcnow() - timedelta(days=days))
    )
    return int(getattr(result, "rowcount", 0) or 0)
