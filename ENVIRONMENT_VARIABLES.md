# Environment Configuration Template for ElderCare

This file documents all environment variables required for ElderCare in production and development.
Copy this template to configure your deployment (e.g. Vercel Project Settings or Google Cloud Run).

---

## 1. Environment & Base Configuration
| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `ENVIRONMENT` | Yes | `development` | Deployment environment (`development`, `test`, `production`). In `production`, strict security rules are enforced at startup. | `production` |
| `APP_BASE_URL` | Yes | `http://localhost:5173` | Canonical public HTTPS URL of the application. Required for secure cookies (`SameSite=Lax`, `Secure`), CSRF matching, and email action links. | `https://eldercare.vercel.app` |
| `SECRET_KEY` | Yes | `dev-only-insecure...` | Cryptographic secret key used for session hashing and security tokens. Must be >= 32 random characters in production. | *(Generate with: `python -c "import secrets; print(secrets.token_urlsafe(48))"`)* |
| `LOG_LEVEL` | No | `INFO` | Application log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |
| `CORS_ORIGINS` | No | `[]` | Comma-separated list of additional allowed CORS origins (if API and SPA are hosted on separate domains). | `["https://eldercare.vercel.app"]` |

---

## 2. Database (PostgreSQL)
| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `DATABASE_URL` | Yes | `sqlite:///./eldercare.db` | PostgreSQL connection string. Must start with `postgresql+psycopg://` or `postgresql://`. SQLite is rejected in production mode. | `postgresql+psycopg://user:password@ep-host.eu-west-1.aws.neon.tech/eldercare?sslmode=require` |

---

## 3. Session & Security
| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `SESSION_TTL_HOURS` | No | `168` (7 days) | Session duration in hours before re-authentication is required. | `168` |
| `SESSION_COOKIE_NAME` | No | `ec_session` | Name of the HttpOnly session cookie. | `ec_session` |
| `CSRF_COOKIE_NAME` | No | `ec_csrf` | Name of the non-HttpOnly CSRF cookie read by the frontend. | `ec_csrf` |
| `LOGIN_MAX_FAILURES` | No | `5` | Maximum failed login attempts within window before rate limiting. | `5` |
| `LOGIN_WINDOW_MINUTES`| No | `15` | Sliding window in minutes for login attempt rate limiting. | `15` |
| `INVITATION_TTL_HOURS` | No | `72` | Expiration time for care circle invitations. | `72` |

---

## 4. Email Provider (SMTP)
| Variable | Required in Prod | Default | Description | Example |
|---|---|---|---|---|
| `EMAIL_TRANSPORT` | Yes | `console` | `smtp` for live email delivery, `console` for local logs. | `smtp` |
| `EMAIL_FROM` | Yes | `ElderCare <no-reply@eldercare.local>` | Verified sender email name and address. | `ElderCare <no-reply@yourdomain.com>` |
| `SMTP_HOST` | If `smtp` | `""` | SMTP relay server host (e.g. Resend, SendGrid, Postmark, AWS SES, Gmail). | `smtp.resend.com` |
| `SMTP_PORT` | No | `587` | SMTP server port (usually 587 with STARTTLS or 465 with SSL). | `587` |
| `SMTP_USERNAME` | If `smtp` | `""` | SMTP authentication username. | `resend` |
| `SMTP_PASSWORD` | If `smtp` | `""` | SMTP authentication password / API key. | `re_123456789...` |
| `SMTP_STARTTLS` | No | `true` | Whether to enable STARTTLS for secure connection. | `true` |

---

## 5. Storage (Medical Documents)
| Variable | Required in Prod | Default | Description | Example |
|---|---|---|---|---|
| `STORAGE_BACKEND` | Yes | `local` | `gcs` for Google Cloud Storage, or `local` for local directory. (In ephemeral serverless like Vercel or Cloud Run, `gcs` must be used). | `gcs` |
| `GCS_BUCKET` | If `gcs` | `""` | Private Google Cloud Storage bucket name for medical documents. | `eldercare-prod-documents` |
| `MAX_UPLOAD_BYTES` | No | `10485760` (10MB) | Maximum file size for uploaded documents. | `10485760` |

---

## 6. AI Assistant (Gemini / Vertex)
| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `AI_PROVIDER` | No | `offline` | `gemini` (Gemini API key), `vertex` (Google Cloud Vertex AI), or `offline` (deterministic lookup). | `gemini` |
| `AI_MODEL` | No | `gemini-2.5-flash` | Gemini model name. | `gemini-2.5-flash` |
| `GEMINI_API_KEY` | If `gemini` | `""` | Server-side Gemini API key from Google AI Studio. | `AIzaSy...` |
| `VERTEX_PROJECT` | If `vertex` | `""` | Google Cloud project ID for Vertex AI. | `eldercare-prod` |
| `VERTEX_LOCATION` | No | `europe-west2` | Vertex AI compute region. | `europe-west2` |

---

## 7. Background Jobs & Scheduler
| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `JOB_TRIGGER_TOKEN` | Yes | `""` | Shared secret header (`X-Job-Token`) to authenticate `/internal/jobs/tick`. Required for Vercel Cron or external schedulers. | *(Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`)* |
| `JOBS_OIDC_AUDIENCE` | Cloud Run | `""` | Expected OIDC audience if triggered by Google Cloud Scheduler. | `https://eldercare-api...run.app` |
| `JOBS_OIDC_SERVICE_ACCOUNT`| Cloud Run| `""` | Cloud Scheduler service account email. | `eldercare-scheduler@project.iam.gserviceaccount.com` |
| `RUN_INPROCESS_SCHEDULER`| No | `false` | Must remain `false` in production. (Refused if `ENVIRONMENT=production`). | `false` |
