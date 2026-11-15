# Environment variables

All settings are read once at startup (`backend/app/config.py`). When `ENVIRONMENT=production`,
the app refuses to start on an insecure combination, and lists every problem it found.

| Variable | Default | Production | Notes |
|---|---|---|---|
| `ENVIRONMENT` | `development` | `production` | `development`, `test` or `production` |
| `APP_BASE_URL` | `http://localhost:5173` | required, https | Used in email links and to decide whether cookies are `Secure` |
| `DATABASE_URL` | `sqlite:///./eldercare.db` | Secret Manager | PostgreSQL required in production, e.g. `postgresql+psycopg://user:pass@/eldercare?host=/cloudsql/PROJECT:REGION:INSTANCE` |
| `SECRET_KEY` | dev placeholder | Secret Manager | 32+ random characters; keys the token hashes |
| `SESSION_TTL_HOURS` | `168` | | Session lifetime |
| `LOGIN_MAX_FAILURES` / `LOGIN_WINDOW_MINUTES` | `5` / `15` | | Login throttling |
| `EMAIL_TRANSPORT` | `console` | `smtp` | `console` logs subject and recipient only; `memory` is for tests |
| `EMAIL_FROM` | `ElderCare <no-reply@eldercare.local>` | required | |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` | empty / `587` / empty | required for smtp | e.g. `smtp.gmail.com` with a Google Workspace or Gmail app password |
| `SMTP_PASSWORD` | empty | Secret Manager | |
| `SMTP_STARTTLS` | `true` | | |
| `EMAIL_MAX_ATTEMPTS` | `5` | | Attempts before a notification is marked `failed` |
| `STORAGE_BACKEND` | `local` | `gcs` or `db` | `db` stores documents in PostgreSQL (used on Vercel); `local` is refused in production |
| `LOCAL_STORAGE_DIR` | `./var/documents` | | |
| `GCS_BUCKET` | empty | required | Private bucket; the Cloud Run service account needs `roles/storage.objectAdmin` on it |
| `MAX_UPLOAD_BYTES` | `10485760` | | |
| `JOBS_OIDC_AUDIENCE` | empty | required (or token) | The tick URL Cloud Scheduler targets |
| `JOBS_OIDC_SERVICE_ACCOUNT` | empty | recommended | Only tokens for this service account are accepted |
| `JOB_TRIGGER_TOKEN` | empty | optional fallback | Shared secret in the `X-Job-Token` header |
| `RUN_INPROCESS_SCHEDULER` | `false` | refused | Development convenience: ticks once a minute in-process |
| `INVITATION_TTL_HOURS` | `72` | | |
| `FRONTEND_DIST_DIR` | `../frontend/dist` | `/app/static` (set in the image) | Built SPA served by the API |
| `CORS_ORIGINS` | empty | usually empty | Only needed if the SPA is hosted on another origin |
| `AI_PROVIDER` | `offline` | `vertex` recommended | `offline`, `gemini` or `vertex` |
| `AI_MODEL` | `gemini-2.5-flash` | | Gemini model id |
| `GEMINI_API_KEY` | empty | Secret Manager (if `gemini`) | Never exposed to the browser |
| `VERTEX_PROJECT` / `VERTEX_LOCATION` | project from credentials / `europe-west2` | | |
| `AI_TIMEOUT_SECONDS` | `20` | | |
| `AI_MAX_OUTPUT_TOKENS` | `700` | | 64 to 4096 |
| `AI_REQUESTS_PER_WINDOW` / `AI_WINDOW_MINUTES` | `20` / `10` | | Per-user quota |
| `DB_POOL` | `queue` | `null` on serverless | `null` = no client pool, no prepared statements (for transaction poolers) |
| `CRON_SECRET` | empty | Vercel | Vercel Cron sends `Authorization: Bearer <CRON_SECRET>` |
| `LOG_LEVEL` | `INFO` | | |
| `GOOGLE_CLOUD_PROJECT` | set by Cloud Run | | Used to format trace ids for Cloud Logging |
| `DEMO_PASSWORD`, `ALLOW_DEMO_SEED` | | never set | Only for `python -m app.seed_demo` |
