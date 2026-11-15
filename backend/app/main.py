"""FastAPI application factory: middleware, routers, health checks and the SPA."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import (
    appointments,
    assistant,
    auth,
    care_team,
    collab,
    documents,
    insights,
    jobs,
    medications,
    notifications,
    patients,
    reports,
)
from app.config import get_settings
from app.db import SessionLocal
from app.errors import install_error_handlers
from app.logging_setup import configure_logging, gcp_project_var, log_event, trace_id_var

logger = logging.getLogger("eldercare.http")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; object-src 'none'"
    ),
}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_dev_scheduler()) if settings.run_inprocess_scheduler else None
        yield
        if task:
            task.cancel()

    app = FastAPI(
        lifespan=lifespan,
        title="ElderCare API",
        version="1.0.0",
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    install_error_handlers(app)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Correlate logs with the Cloud Run request trace (X-Cloud-Trace-Context: TRACE/SPAN;o=1)
        trace_header = request.headers.get("x-cloud-trace-context", "")
        trace_id_var.set(trace_header.split("/")[0] if trace_header else "")
        gcp_project_var.set(settings_project())
        started = time.perf_counter()

        path = request.url.path
        csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
        if request.method in UNSAFE and path.startswith("/api/"):
            # Double-submit CSRF check: a cross-site page can send the cookie but cannot read
            # it to copy into the header. Combined with SameSite=Lax session cookies.
            header = request.headers.get("x-csrf-token", "")
            if not csrf_cookie or not secrets.compare_digest(header, csrf_cookie):
                return JSONResponse(
                    {
                        "error": {
                            "code": "csrf_failed",
                            "message": "Your session needs refreshing. Reload the page.",
                        }
                    },
                    status_code=403,
                )

        response = await call_next(request)
        if not csrf_cookie:
            response.set_cookie(
                settings.csrf_cookie_name,
                secrets.token_urlsafe(24),
                httponly=False,
                secure=settings.cookie_secure,
                samesite="lax",
                path="/",
            )
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.cookie_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        if not path.startswith("/assets/"):
            log_event(
                logger,
                logging.INFO,
                f"{request.method} {path} {response.status_code}",
                httpRequest={
                    "requestMethod": request.method,
                    "requestUrl": path,
                    "status": response.status_code,
                    "latency": f"{duration_ms / 1000:.3f}s",
                },
            )
        return response

    for module in (
        collab,
        assistant,
        reports,
        auth,
        patients,
        care_team,
        medications,
        appointments,
        documents,
        insights,
        notifications,
        jobs,
    ):
        app.include_router(module.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """Liveness: the process is serving requests."""
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        """Readiness: runs a real query, so a database that accepts connections but cannot
        serve them reports unhealthy instead of passing a reachability check."""
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
        except Exception:
            logger.exception("readiness check failed")
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    _mount_spa(app, Path(settings.frontend_dist_dir))
    return app


async def _dev_scheduler() -> None:
    """Local development only (refused in production by config validation): runs the same
    idempotent tick Cloud Scheduler triggers in production, once a minute."""
    from app.db import utcnow
    from app.services.engine import tick

    def run() -> None:
        with SessionLocal() as db:
            tick(db, utcnow())

    while True:
        try:
            await asyncio.to_thread(run)
        except Exception:  # keep the dev loop alive; errors are logged
            logger.exception("dev scheduler tick failed")
        await asyncio.sleep(60)


def settings_project() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT", "")


def _mount_spa(app: FastAPI, dist: Path) -> None:
    """Serves the built frontend from the same origin, so cookies stay first-party and no
    CORS is needed. Unknown non-API paths fall back to index.html for client routing."""
    index = dist / "index.html"
    if not index.is_file():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith(("api/", "internal/")):
            return JSONResponse(
                {"error": {"code": "not_found", "message": "Not found"}}, status_code=404
            )
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
