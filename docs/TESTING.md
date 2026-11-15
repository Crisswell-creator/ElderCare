# Testing

## Strategy

| Layer | Tool | What it proves |
|---|---|---|
| Backend integration | pytest and FastAPI TestClient against the **Alembic-migrated** schema, with a fresh database per test | Auth, authorisation, isolation, medicines, inventory, doses, engine, adherence, appointments, documents, PDF, audit |
| Time-dependent logic | `clock` fixture that patches `utcnow` across the app | Grace periods, escalation, missed classification, retries and backoff, snooze, DST, without sleeping |
| Frontend unit | Vitest and Testing Library | Dose-state derivation, accessible field wiring, confirmation dialogs, API client CSRF and error handling |
| End-to-end | Playwright against the **production build served by the real API** | The eight user journeys through the real UI, with axe WCAG 2.2 AA scans and a phone viewport |
| Migrations | Alembic on SQLite and PostgreSQL 17 (Docker) | Upgrade, downgrade and drift check; audit triggers block UPDATE and DELETE |
| Container | Docker, production mode | Insecure configuration refused at boot; readiness against PostgreSQL; security headers |

Design rules applied to the tests:

- **Negative assertions have positive twins.** For example, "refused before approval" sits next
  to "allowed after approval".
- **Detectors have exact negative controls.** For example, no insights on gap-free data.
- **Rate-limit tests vary the key** instead of resetting the limiter.
- **The one-page PDF guarantee is tested** with maximum-length input on every field.

## Results (last run, 2026-11-15)

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend && uv run pytest` | **75 passed** |
| Backend coverage | `uv run pytest --cov=app` | **90%** statements |
| Lint | `uv run ruff check .` | clean |
| Format | `uv run ruff format --check .` | clean |
| Types | `uv run mypy app` (strict) | no issues in 37 files |
| Python dependency audit | `uv run pip-audit` | no known vulnerabilities |
| Frontend types | `npm run typecheck` (TS strict) | clean |
| Frontend unit tests | `npm test` | **10 passed** |
| Frontend lint | `npx oxlint src` | 0 errors; 3 warnings (`only-export-components`, a dev fast-refresh notice) |
| npm audit | `npm audit` | 0 vulnerabilities |
| End-to-end | `npm run e2e` | **16 passed** (15 desktop Chrome, 1 Pixel 7) |
| Accessibility | axe-core in e2e (wcag2a/aa, 21aa, 22aa) | 0 serious or critical violations on 10 scanned screens |
| PostgreSQL | migrations 0001–0003 up, down and up, plus `alembic check` and trigger probe | passed; UPDATE and DELETE on `audit_events` rejected |
| Container | `docker build`, production-mode run | builds (425 MB); refuses insecure configuration; `/readyz` ok on PostgreSQL |

## Journey coverage

| Journey | End-to-end | Backend |
|---|---|---|
| 1. Elder creates a profile and adds a medication | yes | `test_medications.py` |
| 2. Family requests access; elder approves selected permissions | yes | `test_access.py` |
| 3. Reminder generated; elder confirms the dose (opening the reminder records nothing) | yes (real scheduler tick) | `test_engine.py::test_full_reminder_then_escalation_flow` |
| 4. Unconfirmed dose escalates to the authorised caregiver | caregiver onboarding and task view only | **full flow with a controlled clock** in `test_engine.py` (grace periods are 15 minutes or more, so not practical in a browser run) |
| 5. Caregiver records a refill; inventory updates | yes | `test_medications.py` |
| 6. Family schedules an appointment; elder sees it | yes | `test_records.py` |
| 7. Doctor visit summary | yes (PDF response) | `test_records.py` (content and one-page fit) |
| 8. Elder revokes the caregiver; access ends | yes | `test_access.py` |

## Phase 9–16 scenarios (end-to-end)

| Scenario | Test |
|---|---|
| Caregiver completes an assigned task and reviews the activity history | "Scenario 4 and 14" |
| Assistant answers from authorised records; urgent question gets safety guidance; caregiver without consent is refused | "Scenario 10" |
| Elder opens emergency contacts (tel: link) and asks the care circle for help; delivery shown honestly | "Scenario 13" |
| Reports and CSV exports respect permissions | "Scenario 15" |
| Accessibility settings persist across reloads | "Accessibility settings persist across reloads" |

The 15 required scenarios map onto these tests plus the original journeys (scenarios 1–3 and 5–9 → Journeys 1–7; scenarios 11 and 12 → Journey 8). Scenario 6 (escalation) is covered with a controlled clock in `test_engine.py`.

## Not covered

- **Backend suite on PostgreSQL:** the backend suite runs on SQLite; PostgreSQL is verified for
  migrations, triggers and readiness only.
- **Real email delivery:** SMTP needs a real account, so delivery is tested with the in-memory
  transport (failures and retries included).
- **Live AI calls:** no live Gemini or Vertex request has been made. Providers are tested with mocked HTTP responses and an offline fallback.
- **GCS document storage:** tested through the local implementation only.
- **Screen-reader testing:** it was not done with a physical screen reader; structure is checked
  by axe and role-based Playwright locators.
