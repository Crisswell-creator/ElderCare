# AI evaluation checklist

These are honest self-assessments with evidence. No scores are claimed. Commands are run from
`backend/` or `frontend/`. Last run: 2026-11-15.

## 1. Code quality
- **Implemented:** modular FastAPI routers, a service layer and pure scheduling functions. React
  pages use a single shared component library. TypeScript and mypy run in strict mode. One error
  envelope and one design-token file.
- **Files:** `backend/app/{api,services}`, `frontend/src/{ui.tsx,styles.css,pages}`
- **Verify:** `uv run ruff check . && uv run ruff format --check . && uv run mypy app`; `npm run typecheck && npx oxlint src`
- **Evidence:** ruff clean; mypy strict: 0 issues in 37 files; tsc strict clean; oxlint 0 errors.
- **Deficiencies:** 3 oxlint `only-export-components` warnings (development fast-refresh only).

## 2. Security
- **Implemented:** argon2id passwords; HMAC-hashed server sessions; CSRF protection; persisted
  throttling; patient isolation (404 for non-members); 12 granular permissions; consent
  workflow; magic-byte upload validation; CSP and HSTS; boot-time production config refusal;
  append-only audit log; Secret Manager.
- **Files:** `docs/SECURITY.md`, `backend/app/{deps,security,main,config}.py`, `api/care_team.py`
- **Verify:** `uv run pytest tests/test_access.py tests/test_auth.py`; `uv run pip-audit`; `npm audit`
- **Evidence:** isolation and revocation tests pass; 0 known vulnerabilities in both ecosystems.
  Two independent reviews found 0 critical or high issues. All 4 medium findings were fixed with
  regression tests, as were most of the low ones; the rest are documented.
- **Deficiencies:** the registration endpoint reveals that an email exists (a documented
  trade-off).

## 3. Efficiency
- **Implemented:** composite indexes on hot paths; one-request dashboards; grouped queries with
  no N+1 on the multi-patient home; keyset pagination; bulk dose materialisation; outbox
  batching with `SKIP LOCKED`; scale-to-zero Cloud Run; multi-stage image without dev tools.
- **Files:** `docs/DATABASE.md`, `services/engine.py`, `api/insights.py`, `Dockerfile`
- **Evidence:** image 425 MB, which is dominated by Python runtime and Google client libraries.
- **Deficiencies:** no load test was run.

## 4. Testing
- **Verify:** `uv run pytest --cov=app`; `npm test`; `npm run e2e`
- **Evidence:** backend 75 passed (90% coverage); frontend unit 10 passed; end-to-end 16 passed,
  covering the 15 product scenarios plus a phone viewport. Migrations and triggers verified on
  PostgreSQL 17.
- **Deficiencies:** Journey 4's escalation is tested in the backend with a controlled clock
  rather than in the browser (grace periods are 15 minutes or more).

## 5. Accessibility (WCAG 2.2 AA target)
- **Implemented:** semantic landmarks and skip link; labelled fields with described errors;
  native dialogs; 44 px targets (52 px in elder mode); 3 px focus ring; text-size setting;
  reduced motion; colour plus text for every state; charts mirrored by data tables.
- **Verify:** axe-core scans inside `npm run e2e`
- **Evidence:** 0 serious or critical violations on 10 screens; no horizontal scroll at 375 px.
- **Deficiencies:** no manual screen-reader pass.

## 6. Problem statement alignment
- **Evidence:** `docs/REQUIREMENTS_TRACEABILITY.md` maps 18 requirements to feature, screen,
  endpoint, table and test.

## 7. Google services
- **Ready:** Vertex AI Gemini (service-account auth, tested with mocks), Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud SQL, Cloud Storage,
  Cloud Scheduler (OIDC verified in code), Cloud Logging (structured JSON with trace).
- **Files:** `cloudbuild.yaml`, `deploy/cloudrun.env.yaml`, `docs/DEPLOYMENT.md`, `api/jobs.py`,
  `logging_setup.py`, `services/storage.py`
- **Status:** **not deployed.** This needs a GCP project with billing and owner approval. No
  claim is made that any Google service is configured yet.

## Pre-submission list
| Item | Status |
|---|---|
| Tests, lint, types, security audit, dependency audit, accessibility | Done (see above) |
| Challenge requirements verified | Done (traceability) |
| Cloud Run deployment verified | **Pending:** needs a GCP project and approval |
| Public repository inspected; exactly one branch; under 10 MB | **Pending:** repository not published. Local candidate is 114 files, about 1.55 MB, on branch `main` |
