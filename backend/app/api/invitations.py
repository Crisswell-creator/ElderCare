"""Joining a care circle: single-use invitation codes, access requests, and the elder's
decision on each request. Every step is written to the activity history."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.care_team import has_elder, require_decider
from app.config import get_settings
from app.db import get_db, utcnow
from app.deps import PatientAccess, get_current_user, patient_access
from app.domain import (
    SUGGESTED,
    MembershipStatus,
    NotificationKind,
    Permission,
    RequestStatus,
    Role,
    normalize_permissions,
)
from app.errors import AppError, Conflict, Forbidden, NotFound
from app.models import AccessRequest, Invitation, Membership, Patient, User
from app.security import hash_token, new_invitation_code, normalize_invitation_code
from app.services import audit, notify, throttle

router = APIRouter(tags=["care team"])


class InvitationCreate(BaseModel):
    intended_role: Literal["family", "caregiver", "elder"]
    note: Annotated[str, Field(max_length=200)] = ""


class InvitationOut(BaseModel):
    id: int
    purpose: str
    intended_role: str
    note: str
    created_at: datetime
    expires_at: datetime
    state: str  # active | redeemed | expired | revoked
    code: str | None = None  # only returned once, at creation


class RedeemIn(BaseModel):
    code: Annotated[str, Field(min_length=6, max_length=20)]
    relationship_label: Annotated[str, Field(max_length=60)] = ""
    message: Annotated[str, Field(max_length=500)] = ""


class RequestOut(BaseModel):
    id: int
    patient_id: int
    patient_name: str
    requester_name: str
    requester_email: str
    requester_email_verified: bool
    requested_role: str
    relationship_label: str
    message: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    suggested_permissions: list[str]


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    permissions: list[Permission] = Field(default_factory=list)


def _deciders(db: Session, patient_id: int) -> list[Membership]:
    rows = db.scalars(
        select(Membership).where(
            Membership.patient_id == patient_id, Membership.status == MembershipStatus.ACTIVE
        )
    ).all()
    return [
        m
        for m in rows
        if m.role == Role.ELDER
        or (m.is_representative and Permission.MANAGE_CARE_TEAM in (m.permissions or []))
    ]


def _request_out(r: AccessRequest, patient: Patient) -> RequestOut:
    role = Role(r.requested_role)
    return RequestOut(
        id=r.id,
        patient_id=r.patient_id,
        patient_name=patient.full_name,
        requester_name=r.requester.full_name,
        requester_email=r.requester.email,
        requester_email_verified=r.requester.email_verified_at is not None,
        requested_role=r.requested_role,
        relationship_label=r.relationship_label,
        message=r.message,
        status=r.status,
        created_at=r.created_at,
        decided_at=r.decided_at,
        suggested_permissions=[p.value for p in SUGGESTED[role]],
    )


# ---- invitations ----------------------------------------------------------------------


def _invitation_out(inv: Invitation, now: datetime, code: str | None = None) -> InvitationOut:
    state = (
        "revoked"
        if inv.revoked_at
        else "redeemed"
        if inv.redeemed_at
        else "expired"
        if inv.expires_at <= now
        else "active"
    )
    return InvitationOut(
        id=inv.id,
        purpose=inv.purpose,
        intended_role=inv.intended_role,
        note=inv.note,
        created_at=inv.created_at,
        expires_at=inv.expires_at,
        state=state,
        code=code,
    )


@router.post(
    "/api/patients/{patient_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    body: InvitationCreate,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> InvitationOut:
    require_decider(access)
    purpose = "join"
    if body.intended_role == "elder":
        if has_elder(db, access.patient.id):
            raise Conflict("This profile is already linked to the elder's own account.")
        purpose = "claim"
    code = new_invitation_code()
    inv = Invitation(
        patient_id=access.patient.id,
        code_hash=hash_token(code),
        purpose=purpose,
        intended_role=body.intended_role,
        note=body.note.strip(),
        created_by_user_id=access.user.id,
        expires_at=utcnow() + timedelta(hours=get_settings().invitation_ttl_hours),
    )
    db.add(inv)
    db.flush()
    audit.record(
        db,
        patient_id=access.patient.id,
        actor=access.user,
        action="invitation.created",
        entity_type="invitation",
        entity_id=inv.id,
        summary=f"{access.user.full_name} created an invitation code for a "
        f"{body.intended_role}" + (f" ({inv.note})" if inv.note else ""),
    )
    db.commit()
    return _invitation_out(inv, utcnow(), code=code)


@router.get("/api/patients/{patient_id}/invitations", response_model=list[InvitationOut])
def list_invitations(
    access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> list[InvitationOut]:
    require_decider(access)
    now = utcnow()
    rows = db.scalars(
        select(Invitation)
        .where(Invitation.patient_id == access.patient.id)
        .order_by(Invitation.created_at.desc())
        .limit(20)
    ).all()
    return [_invitation_out(i, now) for i in rows]


@router.delete(
    "/api/patients/{patient_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_invitation(
    invitation_id: int,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> None:
    require_decider(access)
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.patient_id != access.patient.id:
        raise NotFound("That invitation was not found.")
    if inv.revoked_at is None and inv.redeemed_at is None:
        inv.revoked_at = utcnow()
        audit.record(
            db,
            patient_id=access.patient.id,
            actor=access.user,
            action="invitation.revoked",
            entity_type="invitation",
            entity_id=inv.id,
            summary=f"{access.user.full_name} cancelled an invitation code",
        )
        db.commit()


@router.post(
    "/api/invitations/redeem", response_model=RequestOut, status_code=status.HTTP_201_CREATED
)
def redeem_invitation(
    body: RedeemIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RequestOut:
    """Turns a valid code into a *pending request*. Access starts only after approval."""
    key = f"invite:{user.id}"
    throttle.ensure_allowed(db, key, max_failures=5, window_minutes=15)
    inv = db.scalar(
        select(Invitation).where(
            Invitation.code_hash == hash_token(normalize_invitation_code(body.code))
        )
    )
    now = utcnow()
    if inv is None or inv.revoked_at or inv.redeemed_at or inv.expires_at <= now:
        throttle.note_attempt(db, key, succeeded=False)
        raise AppError(
            "That code is not valid. Codes work once and expire after "
            f"{get_settings().invitation_ttl_hours} hours. Ask for a new one.",
            fields={"code": "Invalid or expired code"},
        )
    existing = db.scalar(
        select(Membership).where(
            Membership.patient_id == inv.patient_id,
            Membership.user_id == user.id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    if existing:
        raise Conflict("You are already part of this care circle.")
    pending = db.scalar(
        select(AccessRequest.id).where(
            AccessRequest.patient_id == inv.patient_id,
            AccessRequest.requester_user_id == user.id,
            AccessRequest.status == RequestStatus.PENDING,
        )
    )
    if pending:
        raise Conflict("You already have a request waiting for approval.")
    throttle.note_attempt(db, key, succeeded=True)
    inv.redeemed_at = now
    inv.redeemed_by_user_id = user.id
    req = AccessRequest(
        patient_id=inv.patient_id,
        requester_user_id=user.id,
        invitation_id=inv.id,
        requested_role=inv.intended_role,
        relationship_label=body.relationship_label.strip(),
        message=body.message.strip(),
    )
    db.add(req)
    db.flush()
    patient = db.get(Patient, inv.patient_id)
    if patient is None:
        raise NotFound("We couldn't find that profile.")
    audit.record(
        db,
        patient_id=patient.id,
        actor=user,
        action="access.requested",
        entity_type="access_request",
        entity_id=req.id,
        summary=f"{user.full_name} asked to join as {inv.intended_role}",
    )
    for decider in _deciders(db, patient.id):
        notify.enqueue(
            db,
            recipient=decider.user,
            kind=NotificationKind.ACCESS_REQUEST,
            dedupe_key=f"access-request:{req.id}:{decider.user_id}",
            subject="Someone asked to join your care circle",
            paragraphs=[
                f"{user.full_name} has asked to join a care circle you manage in ElderCare.",
                "Nothing has been shared yet. Open ElderCare to review the "
                "request and choose exactly what they can see and do.",
            ],
            link_path=f"/p/{patient.id}/care-team",
            patient_id=patient.id,
            send_email=decider.user.email_verified_at is not None,
        )
    db.commit()
    return _request_out(req, patient)


@router.get("/api/patients/{patient_id}/access-requests", response_model=list[RequestOut])
def list_requests(
    access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> list[RequestOut]:
    require_decider(access)
    rows = db.scalars(
        select(AccessRequest)
        .where(
            AccessRequest.patient_id == access.patient.id,
            AccessRequest.status == RequestStatus.PENDING,
        )
        .order_by(AccessRequest.created_at)
    ).all()
    return [_request_out(r, access.patient) for r in rows]


@router.post(
    "/api/patients/{patient_id}/access-requests/{request_id}/decision", response_model=RequestOut
)
def decide_request(
    request_id: int,
    body: DecisionIn,
    access: PatientAccess = Depends(patient_access),
    db: Session = Depends(get_db),
) -> RequestOut:
    require_decider(access)
    req = db.get(AccessRequest, request_id)
    if req is None or req.patient_id != access.patient.id:
        raise NotFound("That request was not found.")
    if req.status != RequestStatus.PENDING:
        raise Conflict("This request has already been decided.")
    now = utcnow()
    req.decided_at = now
    req.decided_by_user_id = access.user.id
    patient = access.patient
    if body.decision == "reject":
        req.status = RequestStatus.REJECTED
        audit.record(
            db,
            patient_id=patient.id,
            actor=access.user,
            action="access.rejected",
            entity_type="access_request",
            entity_id=req.id,
            summary=f"{access.user.full_name} declined {req.requester.full_name}'s request",
        )
        outcome = "was not approved"
    else:
        role = Role(req.requested_role)
        if role == Role.ELDER:
            if has_elder(db, patient.id):
                raise Conflict("This profile is already linked to the elder's account.")
            # Linking the elder's own account hands over full control, so the claimant must
            # have proven their email and must not already hold a role in this circle (which
            # blocks a representative approving a second account of their own).
            if req.requester.email_verified_at is None:
                raise AppError(
                    "The person must confirm their email address before they can "
                    "take over the profile."
                )
            if (
                db.scalar(
                    select(Membership.id).where(
                        Membership.patient_id == patient.id,
                        Membership.user_id == req.requester_user_id,
                    )
                )
                is not None
            ):
                raise Forbidden("Someone who already has a role in this circle cannot claim it.")
            perms = [p.value for p in Permission]
        else:
            perms = [p.value for p in normalize_permissions(body.permissions)]
            if not perms:
                raise AppError(
                    "Choose at least one thing this person may see or do.",
                    fields={"permissions": "Select at least one permission"},
                )
        m = db.scalar(
            select(Membership).where(
                Membership.patient_id == patient.id, Membership.user_id == req.requester_user_id
            )
        )
        if m is None:
            m = Membership(patient_id=patient.id, user_id=req.requester_user_id)
            db.add(m)
        m.role = role
        m.status = MembershipStatus.ACTIVE
        m.revoked_at = None
        m.permissions = perms
        m.is_representative = False
        m.relationship_label = "Self" if role == Role.ELDER else req.relationship_label
        m.notify_dose_reminders = role == Role.ELDER
        m.granted_by_user_id = access.user.id
        if role == Role.ELDER:
            patient.managed_by_representative = False
        req.status = RequestStatus.APPROVED
        db.flush()
        audit.record(
            db,
            patient_id=patient.id,
            actor=access.user,
            action="access.granted",
            entity_type="membership",
            entity_id=m.id,
            summary=(
                f"{req.requester.full_name} linked their own account to this profile"
                if role == Role.ELDER
                else f"{access.user.full_name} approved {req.requester.full_name} as {role.value}"
            ),
            details={"permissions": perms},
        )
        outcome = "was approved"
    notify.enqueue(
        db,
        recipient=req.requester,
        kind=NotificationKind.ACCESS_DECISION,
        dedupe_key=f"access-decision:{req.id}",
        subject="Your ElderCare access request was answered",
        paragraphs=[f"Your request to join a care circle {outcome}."],
        link_path="/",
        patient_id=None,
        send_email=req.requester.email_verified_at is not None,
    )
    db.commit()
    return _request_out(req, patient)


@router.get("/api/access-requests/mine", response_model=list[RequestOut])
def my_requests(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[RequestOut]:
    rows = db.scalars(
        select(AccessRequest)
        .where(AccessRequest.requester_user_id == user.id)
        .order_by(AccessRequest.created_at.desc())
        .limit(20)
    ).all()
    patients = {
        p.id: p
        for p in db.scalars(select(Patient).where(Patient.id.in_({r.patient_id for r in rows})))
    }
    # Before approval the requester only learns the profile name they were invited to.
    return [_request_out(r, patients[r.patient_id]) for r in rows]


@router.post("/api/access-requests/{request_id}/withdraw", response_model=RequestOut)
def withdraw_request(
    request_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RequestOut:
    req = db.get(AccessRequest, request_id)
    if req is None or req.requester_user_id != user.id:
        raise NotFound("That request was not found.")
    if req.status != RequestStatus.PENDING:
        raise Conflict("This request has already been decided.")
    req.status = RequestStatus.WITHDRAWN
    req.decided_at = utcnow()
    audit.record(
        db,
        patient_id=req.patient_id,
        actor=user,
        action="access.withdrawn",
        entity_type="access_request",
        entity_id=req.id,
        summary=f"{user.full_name} withdrew their request to join",
    )
    db.commit()
    patient = db.get(Patient, req.patient_id)
    if patient is None:
        raise NotFound("We couldn't find that profile.")
    return _request_out(req, patient)
