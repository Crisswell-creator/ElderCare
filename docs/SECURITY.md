# Security and healthcare safety

## Controls

| Area | Control | Where |
|---|---|---|
| Passwords | argon2id, 10 to 128 characters, common-password and low-variety rejection, transparent rehash | `security.py`, `api/auth.py` |
| Sessions | Random 256-bit token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` over https); only an HMAC-SHA256 of it is stored; revoked on logout, password change and reset | `api/auth.py`, `deps.py` |
| CSRF | Double-submit token required on every state-changing `/api` request, on top of SameSite cookies | `main.py` |
| Account discovery | Identical responses and timing for unknown email on login (dummy hash verify) and on password reset | `api/auth.py` |
| Known trade-off | Registration says "already exists" for a registered email (usability for elders); login and reset never reveal it | `api/auth.py` |
| Brute force | Persisted throttling: 5 failed logins in 15 minutes per account; 5 bad invitation codes per user; 5 wrong current passwords on change; 3 reset emails per hour | `services/throttle.py` |
| Data isolation | Every patient route resolves an *active* membership; non-members get 404; child records are checked against the patient in the path | `deps.py`, every router |
| Least privilege | 12 granular permissions; managing implies viewing; approval needs at least one explicit permission; only the elder designates representatives; nobody can remove the elder | `domain.py`, `api/care_team.py` |
| Elder claim | Taking over a profile requires a verified email from someone with no existing role in the circle (blocks self-approval via a second account) | `api/care_team.py` |
| Consent | Invitation codes are hashed, single-use, expire after 72 hours and only create a pending request; every grant, change and revocation is audited and notified | `api/care_team.py` |
| Input validation | Pydantic models with lengths, patterns, enums and ranges on every input; time zones checked against the IANA database | all routers |
| Injection | SQLAlchemy parameter binding throughout; no string-built SQL; `LIKE` patterns built only from server-generated keys or a `^[a-z_]+$`-validated category | |
| Uploads | Type decided from magic bytes (PDF, PNG, JPEG) not the client's claim; 10 MB cap read with a bounded read; random storage keys; sanitised filenames; downloads only through an authorised endpoint with `attachment`, `nosniff` and `no-store` | `api/documents.py`, `services/storage.py` |
| Headers | CSP `default-src 'self'` (no inline script), `frame-ancestors 'none'`, `X-Frame-Options`, `nosniff`, Referrer-Policy, Permissions-Policy, COOP, HSTS over https; `Cache-Control: no-store` on the API | `main.py` |
| Errors | One envelope; unhandled exceptions return a generic message, with details only in server logs | `errors.py` |
| Secrets | None in the repository; production secrets come from Secret Manager; boot fails on a default `SECRET_KEY`, SQLite, plain http, local document storage or unprotected job endpoints | `config.py`, DEPLOYMENT.md |
| Job endpoint | Google-signed OIDC token checked for audience, service account and verified email; shared-token fallback compared in constant time | `api/jobs.py` |
| Audit | Append-only `audit_events`, enforced by database triggers | migration 0001 |
| Email privacy | No medicine names, doses or conditions in any subject or body; reminders link back to the app; account-security tokens are never stored in the outbox | `services/engine.py`, `api/auth.py` |
| Production surface | OpenAPI and `/api/docs` disabled in production; non-root container user; no server header | `main.py`, `Dockerfile` |

## AI assistant safety

- **Context.** The context sent to a provider is built from the caller's permissions, section
  by section. Others need the elder's explicit `use_assistant` consent.
- **Fixed replies.** Urgent-symptom and medication-change requests get fixed replies with no
  model call. Recent user turns are also checked, so a clinical request split across messages
  still gets the referral.
- **System prompt.** It forbids diagnosis, prescribing, invented facts and any claim to have
  contacted someone.
- **No keys in the frontend.** The Vertex provider uses the service account; the Gemini key, if
  used, lives in Secret Manager.
- **No logging of content.** Prompts and answers are never logged or stored. There is a per-user
  quota, a timeout, and a fallback to the offline record lookup.

## Independent reviews

| Review | Critical/high | Medium | Low | Status |
|---|---|---|---|---|
| Phases 1–8 | 0 | 2 (representative elder-claim via a second account; one representative demoting another) | 4 | Mediums fixed with tests; lows partly fixed (change-password throttle, unverified-email flag, safe `next`), and registration enumeration documented as a trade-off |
| Phases 9–13 | 0 | 2 (activity leaked note text; notes could reference another circle's appointment) | 4 | Mediums fixed with tests; lows fixed except the help-alert double-tap race (documented) |

## Data retention

- **Removing a medicine archives it.** Its doses and stock ledger are kept as part of the care
  record.
- **Removing a document hides it** from the care circle. Permanent erasure of the stored object,
  for example on a data-subject request, is an operator procedure: delete the GCS object and
  record the request.
- **Throttling records are purged after 7 days.** This runs on every scheduler tick.
- **The audit history cannot be deleted** through the application. Deleting a whole profile is a
  supervised operator action that requires disabling the trigger inside a transaction.

## Healthcare safety

- **ElderCare only records.** It never suggests, changes or stops a medicine. The UI repeats
  "as recorded" wherever doses appear.
- **Missed-dose escalations say plainly that they are not emergency alerts.** The Today screen
  states that ElderCare does not contact emergency services and offers one-tap calls to the
  elder's own emergency contacts.
- **Opening a notification never records a dose.** Only an explicit Taken or Skip action does,
  and it records who, when and in what role.
- **Unconfirmed doses are never counted as missed** in analytics.
- **Insights need enough data.** They require a minimum sample and a minimum difference, and
  they state the period and sample size.
- **No AI assistant is included,** so there is no generated medical content.

## Reporting

Report security problems privately to the repository owner rather than opening a public issue.
