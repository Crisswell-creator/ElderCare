"""Activity history writer. Called inside the same transaction as the change it records,
so a change and its audit entry commit or roll back together."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User


def record(
    db: Session,
    *,
    patient_id: int | None,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            patient_id=patient_id,
            actor_user_id=actor.id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary[:300],
            details=details or {},
        )
    )


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Field-level change set, e.g. {"strength": ["5 mg", "10 mg"]}."""
    return {
        key: [_jsonable(before.get(key)), _jsonable(value)]
        for key, value in after.items()
        if before.get(key) != value
    }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool | list | dict):
        return value
    return str(value)
