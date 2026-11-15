"""Scheduled-job trigger. In production, Cloud Scheduler sends an OIDC ID token signed by
Google for a dedicated service account; the token's audience and email are verified here.
A shared secret header is accepted as an alternative for local or non-GCP schedulers."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.errors import Unauthorized
from app.logging_setup import log_event
from app.security import constant_time_equals
from app.services.engine import tick

router = APIRouter(prefix="/internal/jobs", include_in_schema=False)
logger = logging.getLogger("eldercare.jobs")


def _verify_google_oidc(token: str, audience: str, expected_email: str) -> bool:
    try:  # optional 'gcp' extra; without it OIDC tokens are simply not accepted
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError:
        return False

    try:
        claims = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            token, google_requests.Request(), audience
        )
    except ValueError:
        return False
    if expected_email and claims.get("email") != expected_email:
        return False
    return bool(claims.get("email_verified", False))


def authorize_job(request: Request) -> None:
    settings = get_settings()
    auth = request.headers.get("authorization", "")
    if (
        settings.jobs_oidc_audience
        and auth.startswith("Bearer ")
        and _verify_google_oidc(
            auth.removeprefix("Bearer "),
            settings.jobs_oidc_audience,
            settings.jobs_oidc_service_account,
        )
    ):
        return
    if (
        settings.cron_secret
        and auth.startswith("Bearer ")
        and constant_time_equals(auth.removeprefix("Bearer "), settings.cron_secret)
    ):
        return  # Vercel Cron
    shared = request.headers.get("x-job-token", "")
    if (
        settings.job_trigger_token
        and shared
        and constant_time_equals(shared, settings.job_trigger_token)
    ):
        return
    log_event(logger, logging.WARNING, "rejected job trigger", path=request.url.path)
    raise Unauthorized("Not allowed.")


@router.get("/tick", dependencies=[Depends(authorize_job)])  # Vercel Cron uses GET
@router.post("/tick", dependencies=[Depends(authorize_job)])
def run_tick(db: Session = Depends(get_db)) -> dict[str, object]:
    report = tick(db, utcnow())
    return {
        "doses_created": report.doses_created,
        "became_unconfirmed": report.became_unconfirmed,
        "became_missed": report.became_missed,
        "queued": dict(report.queued),
        "delivery": report.delivery,
    }
