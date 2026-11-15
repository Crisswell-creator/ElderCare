"""Request dependencies: authentication and per-patient authorization.

Authorization is always resolved server-side from the caller's *active* membership in the
requested patient's care circle. A caller with no membership gets 404 rather than 403, so
the API never confirms that a profile they cannot see exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.domain import ALL_PERMISSIONS, MembershipStatus, Permission, Role
from app.errors import Forbidden, NotFound, Unauthorized
from app.models import Membership, Patient, User, UserSession
from app.security import hash_token

DbSession = Session


def get_current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise Unauthorized("Please sign in to continue.")
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    now = utcnow()
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= now
        or not session.user.is_active
    ):
        raise Unauthorized("Your session has ended. Please sign in again.")
    # Touch at most every 5 minutes to avoid a write on every request.
    if now - session.last_seen_at > timedelta(minutes=5):
        session.last_seen_at = now
        db.commit()
    return session


def get_current_user(session: UserSession = Depends(get_current_session)) -> User:
    return session.user


@dataclass(frozen=True)
class PatientAccess:
    user: User
    patient: Patient
    membership: Membership

    @property
    def is_elder(self) -> bool:
        return self.membership.role == Role.ELDER

    @property
    def permissions(self) -> frozenset[str]:
        if self.is_elder:
            return frozenset(ALL_PERMISSIONS)
        return frozenset(self.membership.permissions or [])

    def can(self, perm: Permission) -> bool:
        return perm in self.permissions

    def require(self, perm: Permission) -> None:
        if not self.can(perm):
            raise Forbidden("You don't have permission to do that for this person.")

    @property
    def can_decide_access(self) -> bool:
        """The elder decides; a trusted representative may decide on their behalf."""
        return self.is_elder or (
            self.membership.is_representative and self.can(Permission.MANAGE_CARE_TEAM)
        )


def load_access(db: Session, user: User, patient_id: int) -> PatientAccess:
    membership = db.scalar(
        select(Membership).where(
            Membership.patient_id == patient_id,
            Membership.user_id == user.id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    if membership is None:
        raise NotFound("We couldn't find that profile.")
    return PatientAccess(user=user, patient=membership.patient, membership=membership)


def patient_access(
    patient_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PatientAccess:
    return load_access(db, user, patient_id)


def requires(*perms: Permission) -> Callable[..., PatientAccess]:
    def dep(access: PatientAccess = Depends(patient_access)) -> PatientAccess:
        for perm in perms:
            access.require(perm)
        return access

    return dep
