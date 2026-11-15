# Architecture

## Overview

```
Browser (React SPA) ──HTTPS, same origin──▶ Cloud Run service (FastAPI + static SPA)
                                              │  SQLAlchemy 2 (sync), Alembic
                                              ├──▶ PostgreSQL (Cloud SQL or any Postgres)
                                              ├──▶ Cloud Storage (private bucket: documents)
                                              ├──▶ SMTP provider (email outbox delivery)
                                              └──▶ stdout JSON logs ──▶ Cloud Logging
Cloud Scheduler ──OIDC token, every 5 min──▶ POST /internal/jobs/tick (reminder engine)
```

There is one container and one origin. The SPA is served by the API, so session cookies stay
first-party (`SameSite=Lax`, `HttpOnly`) and no CORS is needed. For local development, the Vite
dev server proxies `/api` to the same backend.

## Backend (`backend/app`)

| Module | Responsibility |
|---|---|
| `config.py` | Typed settings from environment variables. Production refuses insecure configuration at boot. |
| `db.py` | Engine and session factory. `UTCDateTime` stores aware UTC datetimes. |
| `models.py` | ORM models. Every patient-scoped table carries `patient_id`. |
| `domain.py` | Enums: roles, the 12 permissions, dose, notification and appointment states. |
| `deps.py` | Authentication (session cookie) and per-patient authorisation (`requires(...)`). |
| `errors.py` | One JSON error envelope. Unhandled errors are logged and answered generically. |
| `logging_setup.py` | JSON logs with Cloud Logging `severity` and trace correlation. |
| `api/*.py` | Routers by domain: auth, patients, care team members, invitations and access requests, medications, doses, appointments, documents, insights, notifications, jobs. |
| `services/doses.py` | Dose lifecycle: generation, state rules, confirmation, undo, snooze. |
| `services/schedule.py` | Pure time-zone and DST schedule arithmetic, plus stock estimates. |
| `services/engine.py` | The reminder engine tick. |
| `services/notify.py` | Outbox: idempotent enqueue, delivery with retries and backoff. |
| `services/inventory.py` | Stock ledger. Negative stock is impossible. |
| `services/adherence.py` | Adherence statistics and evidence-gated insights. |
| `services/visit_pdf.py` | One-page visit summary PDF (fpdf2, embedded Atkinson Hyperlegible). |
| `api/collab.py` | Care tasks, shared notes, help alerts and their delivery status |
| `api/assistant.py`, `services/assistant.py` | Assistant: permission-filtered context, safety gates, Gemini API, Vertex AI and offline providers |
| `api/reports.py` | Period reports and CSV exports |
| `services/storage.py` | Private document storage: local disk for development, GCS for production. |

### Authorisation model

`deps.patient_access` resolves the caller's *active* `Membership` for the `patient_id` in the
URL. A non-member gets **404**, so the API never confirms that a profile exists. `requires(*perms)`
then checks granular permissions. The elder implicitly holds all of them. Every lookup of a child
record by id (medication, dose, appointment, document, question) also checks
`record.patient_id == access.patient.id`, so a guessed id from another circle is a 404.

### Reminder engine

`tick(now)` is idempotent and safe to run concurrently:

1. **Materialise** dose rows for active schedules in `[now-24h, now+36h)`. A unique key on
   `(medication_id, scheduled_at)` makes this idempotent. Doses are only generated from
   `schedule_anchor_at` (set on creation, resume and schedule edits), so an edit never
   back-fills doses nobody was asked to take.
2. **Advance states.** A dose becomes `unconfirmed` after the grace period and `missed` after
   the missed window. Both windows are configurable per elder.
3. **Escalate** every currently unconfirmed dose to members who follow medicines and have
   escalation emails enabled, with one message per time slot. A dedupe key guarantees a single
   send, even when a screen refresh moved the state between ticks.
4. **Dose reminders** at the due time, plus one more after each snooze.
5. **Appointment reminders.** Only the nearest due offset is sent, so a booking made late never
   triggers a burst of stale reminders.
6. **Low-stock warnings**, at most once per medicine per ISO week.
7. **Deliver** the outbox. Rows are locked with `FOR UPDATE SKIP LOCKED` on PostgreSQL, failures
   retry with exponential backoff up to `EMAIL_MAX_ATTEMPTS`, and a status of `sent` means the
   mail server accepted the message.

Confirming a dose withdraws its queued reminder and escalation emails if every dose in that time
slot has been recorded.

## Frontend (`frontend/src`)

React 19, TypeScript strict, Vite, React Router, TanStack Query and lucide icons. There is no UI
kit: `ui.tsx` holds the single implementation of each component (Button, fields, Modal on native
`<dialog>`, ConfirmDialog, toasts, badges, empty, loading and error states). `styles.css` holds
the design tokens. `session.tsx` provides the session and current-patient context. Screens live
in `pages/`. `Shell.tsx` builds role-specific navigation: five plain items for the elder, a
records-oriented menu for family and a task-first menu for caregivers, plus a bottom tab bar on
phones.

## Key decisions

| Decision | Why |
|---|---|
| One Cloud Run container serving API and SPA | One deploy, first-party cookies, no CORS, a small attack surface |
| Server-side sessions, not JWTs | Instant revocation on logout or password change; tokens are stored only as HMAC hashes |
| Persisted throttling (`auth_attempts`) | Rate limits must hold across Cloud Run instances |
| Database-backed outbox and engine, triggered by Cloud Scheduler | Serverless instances have no reliable in-memory timers; state survives restarts and deploys |
| Distinct `unconfirmed` and `missed` states | An unrecorded dose is not evidence it was missed |
| Append-only audit via database triggers | No application bug or ad-hoc session can rewrite history |
| Refusing insecure production settings at boot | A misconfigured deploy fails loudly instead of running unsafely |
| Atkinson Hyperlegible typeface | Designed by the Braille Institute for low-vision readers, which suits this audience |

## Assistant design

1. **Context.** `build_context` assembles only the sections the caller may view (profile,
   medicines and stock, today's doses, adherence, appointments and questions). It never includes
   contacts, documents or access data. Non-elders also need the elder's `use_assistant`
   permission, because asking sends part of the elder's record to an AI provider.
2. **Safety gates.** These run before any model call. Urgent-symptom wording returns fixed
   urgent-care guidance. Medication start, stop or change and diagnosis requests return a fixed
   referral plus the instructions as recorded. Recent user turns are checked too.
3. **Providers.** `vertex` uses Gemini on Vertex AI with the Cloud Run service account, so no
   key exists. `gemini` uses the Gemini API with a server-side key. `offline` is a deterministic
   lookup of the records. On a timeout or error the answer falls back to the offline lookup, and
   the reply says so.
4. **Privacy and quota.** History is held in the browser and sent capped at 10 turns.
   Prompts and answers are never stored or logged; only provider, latency and token counts are.
   Each user has a quota of 20 questions per 10 minutes.

## Clock

All timestamps, including ORM defaults, come from `db.utcnow` and are resolved at call time.
Tests replace that single function to travel in time.
