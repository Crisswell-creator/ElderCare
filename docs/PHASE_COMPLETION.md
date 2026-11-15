# Phase completion

Status as of 2026-11-15. "Verified" means an automated test or a recorded browser check exercised
it. See TESTING.md for the commands and results.

## Phases 1–8 (foundation through visit summary)

All complete and verified. They remain functional: the full backend suite (75 tests) and the
end-to-end suite (16 tests) were re-run after Phases 9–16.

## Phases 9–16

| Phase | Status | What was built | Evidence |
|---|---|---|---|
| 9. Collaboration | Complete, verified | Care tasks (assign, reassign, start, done with note, cancel, reopen, overdue); shared notes in four kinds (note, care instruction, appointment preparation, update), permission-scoped and pinnable; activity timeline filtered by person, kind and date, with before→after values; access history link; task-assignment notifications | `test_phase9_13.py` task, notes and activity tests; e2e "Scenario 4 and 14" |
| 10. AI assistant | Complete, verified with the offline provider and mocked Gemini and Vertex | Permission-aware context, section by section; the elder's consent (`use_assistant`) required for other people; fixed safety replies for urgent symptoms and medication-change requests (no model call, recent turns checked too); Gemini API, Vertex AI and offline providers; fallback on provider failure; per-user quota; timeouts; prompts never logged; chat UI with sources, provider, privacy and safety notices; voice input that only fills the box | `test_phase9_13.py` assistant tests (consent, context filtering, safety gates, fallback, validation, quota, Gemini request shape, Vertex auth failure); e2e "Scenario 10" |
| 11. Alerts and emergency | Complete, verified | Severity levels (info, reminder, warning, critical) with filter, failure visibility and attempt counts; emergency contacts with call order, open to every member; Emergency screen with `tel:` calls; "Ask my care circle for help" with confirmation, 10-minute dedupe and a delivery status read from outbox records; copy never claims emergency services were contacted | `test_help_alert_is_honest_about_delivery_and_rate_limited`; e2e "Scenario 13"; mobile screenshot |
| 12. Accessibility and voice | Complete, verified | Settings saved to the account: high contrast, reduced motion, simpler menu, read-aloud; text size from Phase 2; "Read my day aloud" (speech synthesis, read-only); speech-to-text in the assistant (never auto-sends); everything works without voice | `test_accessibility_preferences_persist`; e2e settings test; axe scans on 9 screens |
| 13. Reports | Complete, verified | Period report: weekly adherence, appointments (attended, cancelled, upcoming, past-unrecorded), tasks by person (alphabetical, no ranking), refills, actions per person; CSV exports for doses, appointments and tasks (permission-checked, audited, formula-injection safe); visit summary PDF from Phase 8 | `test_reports_match_records_and_exports_respect_permissions`; e2e "Scenario 15" |
| 14. Production and Google Cloud | Ready; **not deployed** | Vertex AI provider using the Cloud Run service account (no key); Gemini API option; config validation for AI settings; Cloud Build, Cloud Scheduler OIDC, Secret Manager, Cloud Logging JSON, GCS documents (from earlier phases); DEPLOYMENT.md updated | Unit-tested with mocks; **no live Google call has been made** (no project or credentials available) |
| 15. Security, testing, performance | Complete | Second independent review: 0 critical or high issues; 2 medium and 4 low issues fixed with regression tests; frontend split into lazy-loaded routes (initial JS 135 → 114 KB gzipped); migrations re-verified on PostgreSQL 17; ORM timestamps moved onto one overridable clock | See TESTING.md |
| 16. Polish and readiness | Complete locally | UI review of new screens at desktop and 375 px; docs updated; PROJECT_OVERVIEW.md written | Screenshots; this file |

## External setup still required

1. **Google Cloud project with billing:** deploy with `cloudbuild.yaml` (DEPLOYMENT.md). Owner
   approval is needed because this creates billable resources.
2. **AI provider:** set `AI_PROVIDER=vertex` on Cloud Run and grant the service account
   `roles/aiplatform.user`, or set `AI_PROVIDER=gemini` plus `GEMINI_API_KEY` in Secret Manager.
   Until then the assistant runs in offline record-lookup mode and says so in the UI.
3. **SMTP credentials:** stored in Secret Manager.
4. **Publish:** create the public GitHub repository with a single `main` branch after owner
   approval.

## Known limitations

- **Real external services:** no live Gemini or Vertex call has been made, and no real email has
  been delivered.
- **Help-alert double-tap:** two simultaneous taps can send two alerts, because the 10-minute
  dedupe is a check-then-insert.
- **Tasks have no separate view permission.** Every member of the care circle can see task
  titles.
- **Backend tests run on SQLite.** PostgreSQL is verified for migrations, triggers and readiness.
