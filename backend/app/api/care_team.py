"""Care circle members: granular permissions, trusted representatives, personal reminder
preferences and revocation. Joining (invitations and access requests) is in invitations.py.
Every change is written to the activity history."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import PatientAccess, get_owned, patient_access
from app.domain import (
    MembershipStatus,
    NotificationKind,
    Permission,
    Role,
    normalize_permissions,
)
from app.errors import AppError, Forbidden, NotFound
from app.models import Membership, User
from app.services import audit, notify

router = APIRouter(tags=["care team"])


class MemberOut(BaseModel):
    id: int
    user_id: int
    full_name: str
    email: str
    role: str
    relationship_label: str
    permissions: list[str]
    is_representative: bool
    is_me: bool
    joined_at: datetime
    notify_dose_reminders: bool
    notify_escalations: bool
    notify_appointments: bool
    notify_low_stock: bool


class MemberUpdate(BaseModel):
    permissions: list[Permission] | None = None
    relationship_label: Annotated[str, Field(max_length=60)] | None = None
    is_representative: bool | None = None


class PreferencesIn(BaseModel):
    notify_dose_reminders: bool
    notify_escalations: bool
    notify_appointments: bool
    notify_low_stock: bool


def _member_out(m: Membership, me: User) -> MemberOut:
    perms = [p.value for p in Permission] if m.role == Role.ELDER else sorted(m.permissions or [])
    return MemberOut(
        id=m.id,
        user_id=m.user_id,
        full_name=m.user.full_name,
        email=m.user.email,
        role=m.role,
        relationship_label=m.relationship_label,
        permissions=perms,
        is_representative=m.is_representative,
        is_me=m.user_id == me.id,
        joined_at=m.created_at,
        notify_dose_reminders=m.notify_dose_reminders,
        notify_escalations=m.notify_escalations,
        notify_appointments=m.notify_appointments,
        notify_low_stock=m.notify_low_stock,
    )


def require_decider(access: PatientAccess) -> None:
    if not access.can_decide_access:
        raise Forbidden(
            "Only the person this profile belongs to, or their trusted "
            "representative, can manage access."
        )


def has_elder(db: Session, patient_id: int) -> bool:
    return (
        db.scalar(
            select(Membership.id).where(
                Membership.patient_id == patient_id,
                Membership.role == Role.ELDER,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
        is not None
    )


# ---- members --------------------------------------------------------------------------


@router.get("/api/patients/{patient_id}/members", response_model=list[MemberOut])
def list_members(
    access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> list[MemberOut]:
    rows = db.scalars(
        select(Membership)
        .where(
            Membership.patient_id == access.patient.id, Membership.status == MembershipStatus.ACTIVE
        )
        .order_by(Membership.created_at)
    ).all()
    return [_member_out(m, access.user) for m in rows]


def _get_member(db: Session, access: PatientAccess, member_id: int) -> Membership:
    m = get_owned(db, Membership, member_id, access, "person in this care circle")
    if m.status != MembershipStatus.ACTIVE:
        raise NotFound("That person is not in this care circle.")
    return m


@router.patch("/api/patients/{patient_id}/members/{member_id}", response_model=MemberOut)
def update_member(
    member_id: int,
    body: MemberUpdate,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> MemberOut:
    require_decider(access)
    m = _get_member(db, access, member_id)
    if m.role == Role.ELDER:
        raise Forbidden("The elder's own access cannot be changed.")
    if m.is_representative and not access.is_elder and m.user_id != access.user.id:
        # Mirrors revoke_member: one representative may not strip another's authority.
        raise Forbidden("Only the elder can change a trusted representative's access.")
    if m.user_id == access.user.id and not access.is_elder:
        raise Forbidden("Ask the elder to change your own permissions.")
    details: dict[str, object] = {}
    if body.permissions is not None:
        new = [p.value for p in normalize_permissions(body.permissions)]
        if not new:
            raise AppError("Choose at least one permission, or remove the person instead.")
        details["permissions"] = [sorted(m.permissions or []), new]
        m.permissions = new
    if body.relationship_label is not None:
        m.relationship_label = body.relationship_label.strip()
    if body.is_representative is not None and body.is_representative != m.is_representative:
        # Designating someone to act for the elder is the elder's decision; a representative
        # may only do it while no elder account is linked yet.
        if not access.is_elder and has_elder(db, access.patient.id):
            raise Forbidden("Only the elder can choose a trusted representative.")
        m.is_representative = body.is_representative
        if m.is_representative and Permission.MANAGE_CARE_TEAM not in (m.permissions or []):
            granted: set[str] = {*(m.permissions or []), Permission.MANAGE_CARE_TEAM.value}
            m.permissions = sorted(granted)
        details["is_representative"] = m.is_representative
    if details:
        audit.record(
            db,
            patient_id=access.patient.id,
            actor=access.user,
            action="access.permissions_changed",
            entity_type="membership",
            entity_id=m.id,
            summary=f"{access.user.full_name} changed access for {m.user.full_name}",
            details=details,
        )
    db.commit()
    return _member_out(m, access.user)


@router.delete(
    "/api/patients/{patient_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_member(
    member_id: int, access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> None:
    m = _get_member(db, access, member_id)
    leaving = m.user_id == access.user.id
    if m.role == Role.ELDER:
        raise Forbidden("The elder cannot be removed from their own profile.")
    if not leaving:
        require_decider(access)
        if m.is_representative and not access.is_elder:
            raise Forbidden("Only the elder can remove a trusted representative.")
    m.status = MembershipStatus.REVOKED
    revoked_at = utcnow()
    m.revoked_at = revoked_at
    m.is_representative = False
    summary = (
        f"{m.user.full_name} left the care circle"
        if leaving
        else f"{access.user.full_name} removed {m.user.full_name}'s access"
    )
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="access.revoked",
        entity_type="membership",
        entity_id=m.id,
        summary=summary,
    )
    if not leaving:
        notify.enqueue(
            db,
            recipient=m.user,
            kind=NotificationKind.ACCESS_DECISION,
            dedupe_key=f"revoked:{m.id}:{revoked_at.isoformat()}",
            subject="Your ElderCare access has changed",
            paragraphs=[
                "Your access to a care profile in ElderCare has been removed by the profile owner."
            ],
            patient_id=None,
        )
    db.commit()


@router.put("/api/patients/{patient_id}/members/me/preferences", response_model=MemberOut)
def set_preferences(
    body: PreferencesIn,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> MemberOut:
    m = access.membership
    for key, value in body.model_dump().items():
        setattr(m, key, value)
    db.commit()
    return _member_out(m, access.user)
