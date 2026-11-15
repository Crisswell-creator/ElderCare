"""Application settings, validated once at startup from environment variables.

Every value has a safe development default except the ones that must never have one in
production; `Settings.validate_for_production` enforces those so a misconfigured deploy
fails at boot instead of running insecurely.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_base_url: str = "http://localhost:5173"
    database_url: str = "sqlite:///./eldercare.db"
    secret_key: str = Field(default="dev-only-insecure-secret-key-change-me", min_length=32)

    # Sessions
    session_ttl_hours: int = 24 * 7
    session_cookie_name: str = "ec_session"
    csrf_cookie_name: str = "ec_csrf"

    # Login throttling (persisted in the database, so it holds across instances)
    login_max_failures: int = 5
    login_window_minutes: int = 15

    # Email
    email_transport: Literal["console", "memory", "smtp"] = "console"
    email_from: str = "ElderCare <no-reply@eldercare.local>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    email_max_attempts: int = 5

    # Documents
    # "db" keeps document bytes in PostgreSQL: durable on serverless hosts (Vercel) with no
    # extra service. "gcs" uses a private Cloud Storage bucket.
    storage_backend: Literal["local", "gcs", "db"] = "local"
    local_storage_dir: str = "./var/documents"
    gcs_bucket: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024

    # Scheduled jobs. Cloud Scheduler calls /internal/jobs/tick with an OIDC token
    # (jobs_oidc_audience) or, in development, a shared token header.
    job_trigger_token: str = ""
    # Vercel Cron sends "Authorization: Bearer $CRON_SECRET".
    cron_secret: str = ""
    # "null" disables client-side pooling for serverless functions that sit behind a
    # transaction pooler (Supabase Supavisor, PgBouncer).
    db_pool: Literal["queue", "null"] = "queue"
    jobs_oidc_audience: str = ""
    jobs_oidc_service_account: str = ""
    run_inprocess_scheduler: bool = False

    # Invitations
    invitation_ttl_hours: int = 72

    # Static frontend (built SPA) served by the API in the single-container deployment
    frontend_dist_dir: str = "../frontend/dist"
    cors_origins: list[str] = Field(default_factory=list)

    # AI assistant. "offline" needs no credentials (record lookup only); "gemini" uses the
    # Gemini API with a server-side key; "vertex" uses Vertex AI with the service account.
    ai_provider: Literal["offline", "gemini", "vertex"] = "offline"
    ai_model: str = "gemini-2.5-flash"
    gemini_api_key: str = ""
    vertex_project: str = ""
    vertex_location: str = "europe-west2"
    ai_timeout_seconds: float = 20.0
    ai_max_output_tokens: int = Field(default=700, ge=64, le=4096)
    ai_requests_per_window: int = 20
    ai_window_minutes: int = 10

    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_secure(self) -> bool:
        return self.app_base_url.startswith("https://")

    @model_validator(mode="after")
    def validate_for_production(self) -> Settings:
        if not self.is_production:
            return self
        problems: list[str] = []
        if "dev-only" in self.secret_key:
            problems.append("SECRET_KEY must be set to a random value of 32+ characters")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL must point to PostgreSQL in production")
        if not self.app_base_url.startswith("https://"):
            problems.append("APP_BASE_URL must use https in production")
        if self.email_transport == "smtp" and not (self.smtp_host and self.smtp_password):
            problems.append("SMTP_HOST and SMTP_PASSWORD are required for EMAIL_TRANSPORT=smtp")
        if self.storage_backend == "gcs" and not self.gcs_bucket:
            problems.append("GCS_BUCKET is required for STORAGE_BACKEND=gcs")
        if self.storage_backend == "local":
            problems.append("STORAGE_BACKEND=local is not durable on serverless; use gcs or db")
        if not (self.jobs_oidc_audience or self.job_trigger_token or self.cron_secret):
            problems.append(
                "Set JOBS_OIDC_AUDIENCE (or JOB_TRIGGER_TOKEN) to protect job endpoints"
            )
        if self.ai_provider == "gemini" and not self.gemini_api_key:
            problems.append("GEMINI_API_KEY is required for AI_PROVIDER=gemini")
        if self.run_inprocess_scheduler:
            problems.append("RUN_INPROCESS_SCHEDULER is for development; use Cloud Scheduler")
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
