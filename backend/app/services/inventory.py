"""Medication stock ledger. Every change is an InventoryEvent; the cached
`Medication.quantity_on_hand` is only ever moved through `apply`, which forbids negatives."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain import InventoryKind
from app.errors import AppError
from app.models import InventoryEvent, Medication, User


def apply(
    db: Session,
    med: Medication,
    kind: InventoryKind,
    *,
    delta: Decimal | None = None,
    absolute: Decimal | None = None,
    actor: User | None,
    note: str = "",
    dose_event_id: int | None = None,
) -> InventoryEvent | None:
    current = med.quantity_on_hand
    if kind in (InventoryKind.INITIAL, InventoryKind.CORRECTION):
        if absolute is None or absolute < 0:
            raise AppError(
                "The counted quantity must be zero or more.",
                fields={"quantity": "Must be zero or more"},
            )
        new = absolute
    elif kind == InventoryKind.REFILL:
        if delta is None or delta <= 0:
            raise AppError(
                "A refill must add a positive quantity.",
                fields={"quantity": "Must be more than zero"},
            )
        new = (current or Decimal(0)) + delta
    else:  # dose taken / reverted only move stock that is being tracked
        if current is None or delta is None:
            return None
        new = current + delta
        if new < 0:
            # The dose happened; the recorded count was wrong. Clamp and say so, rather
            # than refusing to record a dose or storing an impossible negative stock.
            new = Decimal(0)
            note = (note + " " if note else "") + "Stock reached zero; please recount."
    event = InventoryEvent(
        medication_id=med.id,
        kind=kind,
        quantity_delta=new - (current or Decimal(0)),
        quantity_after=new,
        note=note[:300],
        dose_event_id=dose_event_id,
        actor_user_id=actor.id if actor else None,
    )
    med.quantity_on_hand = new
    db.add(event)
    return event
