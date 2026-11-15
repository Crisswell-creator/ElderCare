"""Assistant endpoint. The context sent to any AI provider is built from the caller's own
permissions for this care circle; conversation history is held by the client and validated
here, and nothing the user types is stored or logged."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.medications import local_today
from app.config import get_settings
from app.db import get_db
from app.deps import PatientAccess, patient_access
from app.domain import Permission
from app.errors import Forbidden
from app.services import assistant, throttle

router = APIRouter(prefix="/api/patients/{patient_id}/assistant", tags=["assistant"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=4000)]


class AskIn(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=1000, pattern=r"\S")]
    history: list[Turn] = Field(default_factory=list, max_length=10)


class AskOut(BaseModel):
    answer: str
    provider: str
    sources: list[str]
    safety: str | None
    notice: str
    disclaimer: str


class InfoOut(BaseModel):
    provider: str
    sources: list[str]
    disclaimer: str
    suggestions: list[str]


def _require(access: PatientAccess) -> None:
    # The elder always may; others need the elder's explicit consent, because asking sends
    # parts of the elder's record to an AI provider.
    if not (access.is_elder or access.can(Permission.USE_ASSISTANT)):
        raise Forbidden(
            "The person this profile belongs to hasn't allowed you to use the "
            "assistant for their records."
        )


@router.get("", response_model=InfoOut)
def info(access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)) -> InfoOut:
    _require(access)
    ctx = assistant.build_context(db, access, local_today(access.patient))
    suggestions = []
    if access.can(Permission.VIEW_MEDICATIONS):
        suggestions += ["What medicines are due today?", "When will any medicine run out?"]
    if access.can(Permission.VIEW_APPOINTMENTS):
        suggestions += [
            "Summarise the upcoming appointments",
            "Help me prepare questions for the doctor",
        ]
    if access.can(Permission.VIEW_ADHERENCE):
        suggestions.append("How has medicine-taking gone this month?")
    suggestions.append("What does \u201cas needed\u201d mean?")
    return InfoOut(
        provider=assistant.provider_for(ctx).name,
        sources=ctx.sources,
        disclaimer=assistant.DISCLAIMER,
        suggestions=suggestions[:6],
    )


@router.post("", response_model=AskOut)
def ask(
    body: AskIn, access: PatientAccess = Depends(patient_access), db: Session = Depends(get_db)
) -> AskOut:
    _require(access)
    s = get_settings()
    throttle.ensure_quota(
        db,
        f"ai:{access.user.id}",
        limit=s.ai_requests_per_window,
        window_minutes=s.ai_window_minutes,
    )
    today = local_today(access.patient)
    ctx = assistant.build_context(db, access, today)
    reply = assistant.respond(ctx, [t.model_dump() for t in body.history], body.message, today)
    return AskOut(
        answer=reply.answer,
        provider=reply.provider,
        sources=reply.sources,
        safety=reply.safety,
        notice=reply.notice,
        disclaimer=assistant.DISCLAIMER,
    )
