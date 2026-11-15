# ElderCare

A shared healthcare coordination platform built around one older person's profile. The elder,
their family and their caregivers manage medicines, doses, refills and doctor appointments
together, and the elder decides who sees what.

Built for the challenge *Elderly Care & Medication Management Platform*. Each challenge requirement
is mapped to its feature, screen, endpoint, table and test in
[docs/REQUIREMENTS_TRACEABILITY.md](docs/REQUIREMENTS_TRACEABILITY.md).

## What it does

- **Elder-controlled access.** Everyone has their own account. The elder shares an expiring,
  single-use invitation code. Using the code only *requests* access. The elder then approves and
  picks from 12 granular permissions, and can change or revoke them at any time. Trusted
  representatives (for example someone with power of attorney) can act with a recorded
  attestation, and the elder can take over later.
- **Medicines and doses.** Schedules support multiple times and weekdays, plus as-needed
  medicines, pausing, stopping, and removal that keeps the history. The six dose states
  (scheduled, taken, skipped, unconfirmed, missed, cancelled) are kept distinct, and each
  recorded dose stores who confirmed it, when, and from which role.
- **Reminder engine.** The database-backed engine is idempotent and time-zone aware. It sends
  dose reminders with snooze, then escalates to authorised carers after a configurable grace
  period. It also sends appointment and low-stock reminders. Emails go through an outbox with
  retries, backoff and duplicate prevention, and carry no medicine names.
- **Inventory ledger.** Every stock change is recorded: refills, corrections and doses taken.
  Stock can never go negative. Run-out dates are estimates and are labelled as estimates.
- **Adherence analytics.** Results are computed from recorded doses only, with the calculation
  rules shown. Unconfirmed doses are never counted as missed. An insight appears only when there
  is enough data, and it shows the period and sample size.
- **Appointments.** List and month calendar, rescheduling and cancellation, reminders,
  calendar (.ics) export, and questions to raise with the doctor.
- **Doctor visit summary.** A one-page printable PDF made only from recorded data.
- **Activity history.** Append-only, enforced by database triggers.
- **Care coordination.** Care tasks with assignment and due dates, shared notes and care
  instructions, and an activity timeline you can filter by person, kind and date.
- **Assistant.** Answers questions using only the records the asking person may see, from
  Gemini on Vertex AI, the Gemini API, or an offline record lookup. Urgent symptoms and
  requests to change a medicine get fixed safety replies.
- **Emergency help.** An emergency screen with one-tap calls to contacts in their set order,
  plus "Ask my care circle for help", whose delivery status comes from real records.
- **Reports.** Period reports and CSV exports, checked against permissions and recorded in the
  activity history.
- **Three distinct interfaces.** Elders get a large-text Today screen. Family members get a
  monitoring dashboard. Caregivers get a task view. All three share one design system and target
  WCAG 2.2 AA.

## Run it locally

Requirements: Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node 22+.

```bash
cd backend
cp .env.example .env            # local settings; never commit real secrets
uv sync --all-extras            # core + server (uvicorn, alembic) + gcp extras
uv run alembic upgrade head
uv run python -m app.seed_demo  # optional: fictional demo data, clearly labelled
uv run uvicorn app.main:app --port 8000
```

```bash
cd frontend
npm ci
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

The demo seed creates `demo.elder@example.com`, `demo.family@example.com` and
`demo.carer@example.com`. Their password comes from the `DEMO_PASSWORD` environment variable,
falling back to the default in `backend/app/seed_demo.py`. Emails are printed to the API log
(`EMAIL_TRANSPORT=console`), and the reminder engine runs once a minute in-process
(`RUN_INPROCESS_SCHEDULER=true`, development only).

## Checks

```bash
cd backend && uv run pytest && uv run ruff check . && uv run mypy app && uv run pyright && uv run pip-audit
cd frontend && npm run typecheck && npm run lint && npm test && npm audit && npm run e2e
```

Results from the last run are recorded in [docs/TESTING.md](docs/TESTING.md) and
[AI_EVALUATION_CHECKLIST.md](AI_EVALUATION_CHECKLIST.md).

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, request flow, reminder engine, design decisions |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema, indexes, migrations, backups |
| [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) | Every endpoint (generated from OpenAPI) |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, controls, retention, healthcare safety |
| [docs/TESTING.md](docs/TESTING.md) | Test strategy and actual results |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Google Cloud Run, Cloud Build, Secret Manager, Cloud Scheduler |
| [docs/ENVIRONMENT_VARIABLES.md](docs/ENVIRONMENT_VARIABLES.md) | Every setting |
| [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) | Visual identity, tokens, components |
| [docs/PHASE_COMPLETION.md](docs/PHASE_COMPLETION.md) | Phase-by-phase status |
| [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | Hackathon overview |
| [docs/REQUIREMENTS_TRACEABILITY.md](docs/REQUIREMENTS_TRACEABILITY.md) | Challenge requirement to code and test |

## Medical safety

ElderCare records what people enter. It never recommends, changes or stops a medicine, never
diagnoses, and never claims to contact emergency services. Missed-dose messages explicitly say
they are not emergency alerts.
