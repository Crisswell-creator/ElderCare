"""Accounts: registration, sign-in/out, email verification, password recovery, profile."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import AfterValidator, BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.deps import get_current_session, get_current_user
from app.domain import MembershipStatus
from app.errors import AppError, Conflict, Unauthorized
from app.models import AuthToken, Membership, User, UserSession
from app.security import hash_password, hash_token, needs_rehash, new_token, verify_password
from app.services import throttle
from app.services.email import send_now

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COMMON = {
    "password123",
    "1234567890",
    "qwertyuiop",
    "iloveyou12",
    "password12",
    "letmein123",
    "welcome123",
    "abc1234567",
    "passw0rd12",
    "0987654321",
    "eldercare1",
    "eldercare123",
}
_TIMEZONES = available_timezones()


def _valid_tz(value: str) -> str:
    if value not in _TIMEZONES:
        raise ValueError("Choose a valid time zone")
    return value


def _valid_password(value: str) -> str:
    if value.lower() in _COMMON or len(set(value)) < 4:
        raise ValueError("This password is too easy to guess. Try a longer phrase.")
    return value


TimeZone = Annotated[str, AfterValidator(_valid_tz)]
Password = Annotated[str, Field(min_length=10, max_length=128), AfterValidator(_valid_password)]
Name = Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]


class RegisterIn(BaseModel):
    email: EmailStr
    password: Password
    full_name: Name
    timezone: TimeZone = "UTC"


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    timezone: str
    text_scale: str
    email_verified: bool
    preferences: Preferences

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            timezone=user.timezone,
            text_scale=user.text_scale,
            email_verified=user.email_verified_at is not None,
            preferences=Preferences.model_validate(user.preferences or {}),
        )


class SessionOut(BaseModel):
    user: UserOut | None


class Preferences(BaseModel):
    contrast: Literal["standard", "high"] = "standard"
    reduce_motion: bool = False
    simplified_nav: bool = False
    read_aloud: bool = True


class ProfileIn(BaseModel):
    full_name: Name | None = None
    timezone: TimeZone | None = None
    text_scale: Literal["standard", "large", "xlarge"] | None = None
    preferences: Preferences | None = None


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: Password


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ResetIn(TokenIn):
    password: Password


class MembershipOut(BaseModel):
    patient_id: int
    patient_name: str
    preferred_name: str
    role: str
    relationship_label: str
    permissions: list[str]
    is_representative: bool


def _start_session(db: Session, response: Response, user: User, request: Request) -> None:
    settings = get_settings()
    token = new_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
            user_agent=(request.headers.get("user-agent") or "")[:255],
        )
    )
    db.commit()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _issue_token(db: Session, user: User, purpose: str, hours: int) -> str:
    token = new_token()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(hours=hours),
        )
    )
    db.commit()
    return token


def _consume_token(db: Session, token: str, purpose: str) -> User:
    row = db.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == hash_token(token), AuthToken.purpose == purpose
        )
    )
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise AppError("This link is invalid or has expired. Please request a new one.")
    row.used_at = utcnow()
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AppError("This link is invalid or has expired. Please request a new one.")
    return user


def _send_verification(db: Session, user: User) -> None:
    token = _issue_token(db, user, "verify_email", hours=48)
    send_now(
        user.email,
        "Confirm your ElderCare email address",
        heading="Confirm your email address",
        paragraphs=[
            f"Hello {user.full_name},",
            "Please confirm this email address so ElderCare can send you reminders and "
            "care updates. The link works once and expires in 48 hours.",
        ],
        action_label="Confirm email address",
        action_url=f"{get_settings().app_base_url}/verify-email?token={token}",
    )


@router.get("/session", response_model=SessionOut)
def session_info(request: Request, db: Session = Depends(get_db)) -> SessionOut:
    """Returns the signed-in user or null. Never 401s, so the SPA can call it on load."""
    try:
        session = get_current_session(request, db)
    except Unauthorized:
        return SessionOut(user=None)
    return SessionOut(user=UserOut.of(session.user))


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> SessionOut:
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict(
            "An account with this email already exists. Try signing in.",
            fields={"email": "Already registered"},
        )
    if body.password.lower() == email:
        raise AppError(
            "Your password must not be your email address.",
            fields={"password": "Must not match your email"},
        )
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name.strip(),
        timezone=body.timezone,
    )
    db.add(user)
    db.commit()
    _send_verification(db, user)
    _start_session(db, response, user, request)
    return SessionOut(user=UserOut.of(user))


@router.post("/login", response_model=SessionOut)
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> SessionOut:
    settings = get_settings()
    email = body.email.lower()
    key = f"login:{email}"
    throttle.ensure_allowed(
        db,
        key,
        max_failures=settings.login_max_failures,
        window_minutes=settings.login_window_minutes,
    )
    user = db.scalar(select(User).where(User.email == email))
    if not verify_password(body.password, user.password_hash if user else None) or (
        user is None or not user.is_active
    ):
        throttle.note_attempt(db, key, succeeded=False)
        raise Unauthorized("That email and password don't match. Please try again.")
    throttle.note_attempt(db, key, succeeded=True)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    _start_session(db, response, user, request)
    return SessionOut(user=UserOut.of(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    session.revoked_at = utcnow()
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return response


@router.post("/verify-email", response_model=UserOut)
def verify_email(body: TokenIn, db: Session = Depends(get_db)) -> UserOut:
    user = _consume_token(db, body.token, "verify_email")
    user.email_verified_at = user.email_verified_at or utcnow()
    db.commit()
    return UserOut.of(user)


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    if user.email_verified_at is None:
        key = f"verify:{user.id}"
        throttle.ensure_allowed(db, key, max_failures=3, window_minutes=60)
        throttle.note_attempt(db, key, succeeded=False)
        _send_verification(db, user)
    return {"status": "accepted"}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(body: EmailIn, db: Session = Depends(get_db)) -> dict[str, str]:
    """Same response whether or not the account exists, to prevent account discovery."""
    email = body.email.lower()
    key = f"reset:{email}"
    throttle.ensure_allowed(db, key, max_failures=3, window_minutes=60)
    throttle.note_attempt(db, key, succeeded=False)
    user = db.scalar(select(User).where(User.email == email, User.is_active))
    if user is not None:
        token = _issue_token(db, user, "reset_password", hours=1)
        send_now(
            user.email,
            "Reset your ElderCare password",
            heading="Reset your password",
            paragraphs=[
                "Someone asked to reset the password for this ElderCare account.",
                "If it was you, use the button below within one hour. If not, you can "
                "ignore this email and your password will stay the same.",
            ],
            action_label="Choose a new password",
            action_url=f"{get_settings().app_base_url}/reset-password?token={token}",
        )
    return {"status": "accepted"}


def _revoke_sessions(db: Session, user_id: int, keep: int | None = None) -> None:
    stmt = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if keep is not None:
        stmt = stmt.where(UserSession.id != keep)
    db.execute(stmt.values(revoked_at=utcnow()))


def _password_changed_notice(user: User) -> None:
    send_now(
        user.email,
        "Your ElderCare password was changed",
        heading="Your password was changed",
        paragraphs=[
            "The password for your ElderCare account was just changed and other signed-in "
            "devices were signed out.",
            "If you did not do this, reset your password now and contact the people in "
            "your care circle.",
        ],
    )


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(body: ResetIn, db: Session = Depends(get_db)) -> Response:
    user = _consume_token(db, body.token, "reset_password")
    user.password_hash = hash_password(body.password)
    user.password_changed_at = utcnow()
    # Proving control of the inbox also verifies the address.
    user.email_verified_at = user.email_verified_at or utcnow()
    _revoke_sessions(db, user.id)
    db.commit()
    _password_changed_notice(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordIn,
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    user = session.user
    key = f"change-password:{user.id}"
    throttle.ensure_allowed(db, key, max_failures=5, window_minutes=15)
    if not verify_password(body.current_password, user.password_hash):
        throttle.note_attempt(db, key, succeeded=False)
        raise AppError(
            "Your current password is not correct.",
            fields={"current_password": "Incorrect password"},
        )
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    _revoke_sessions(db, user.id, keep=session.id)
    db.commit()
    _password_changed_notice(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/me", response_model=UserOut)
def update_me(
    body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserOut:
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return UserOut.of(user)


@router.get("/memberships", response_model=list[MembershipOut])
def my_memberships(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[MembershipOut]:
    rows = db.scalars(
        select(Membership)
        .where(Membership.user_id == user.id, Membership.status == MembershipStatus.ACTIVE)
        .order_by(Membership.created_at)
    ).all()
    return [
        MembershipOut(
            patient_id=m.patient_id,
            patient_name=m.patient.full_name,
            preferred_name=m.patient.preferred_name,
            role=m.role,
            relationship_label=m.relationship_label,
            permissions=sorted(m.permissions or []),
            is_representative=m.is_representative,
        )
        for m in rows
    ]
