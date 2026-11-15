# ElderCare: project overview

## Problem

Older people often manage several medicines and appointments, while family and carers try to
help from different places with no shared picture. Reminder apps cover the elder alone. Shared
documents and group chats spread health details with no control. The challenge asks for a
connected platform that keeps everyone informed while the elder stays in charge of their own
care.

## Solution

ElderCare is one shared healthcare profile per older person. Everyone has their own account and
joins through an expiring, single-use code. The elder approves each person and chooses exactly
what they can see and do, from 14 permissions, and can revoke access at any time. Medicines,
doses, stock, appointments, tasks, notes and documents live in that profile. Reminders and
escalations reach the right people by email and in the app.

## Users

| User | What they get |
|---|---|
| The elder | A large-text Today screen with one-tap Taken and Skip, emergency calls, an assistant, and full control of access |
| Family members | A monitoring dashboard with adherence trends, visits, activity and refill warnings |
| Caregivers | A task view: what to do now, assigned tasks, dose recording and refills |
| Trusted representatives | Can act for an elder who can't manage an account, with a recorded attestation; the elder can take over later |

## Core features

- **Medicines:** medication schedules with distinct dose states (taken, skipped, unconfirmed,
  missed, cancelled) and a record of who confirmed each dose.
- **Reminders:** dose reminders, escalation after a grace period, and appointment and refill
  reminders, through a reliable email outbox with retries.
- **Inventory:** a stock ledger with labelled run-out estimates.
- **Adherence analytics:** never counts an unconfirmed dose as missed; shows its rules, the
  sample size, and insights only when the evidence supports them.
- **Coordination:** appointments with calendar and .ics export, questions for the doctor, and a
  one-page visit summary PDF.
- **Shared work:** care tasks, shared notes, and an append-only activity timeline with filters
  and before→after values.
- **Assistant:** answers only from records the user may see; fixed safety responses for urgent
  or clinical questions.
- **Emergency:** an emergency screen with calls, plus a help request to the care circle that
  reports delivery honestly.
- **Reports and exports:** CSV and PDF, all permission-checked and audited.

## Architecture

The app is one container. FastAPI serves the API and the built React SPA from the same origin.
PostgreSQL holds the data and Cloud Storage holds documents. Cloud Scheduler triggers an
idempotent reminder engine every five minutes. Details are in ARCHITECTURE.md.

## Security approach

- **Accounts:** argon2id passwords; server-side sessions; CSRF protection; persisted throttling.
- **Isolation:** every patient route resolves an active membership, and child records are checked
  against the patient.
- **Audit:** an append-only log enforced by database triggers.
- **Privacy:** emails contain no medicine names; the AI context is filtered to the user's
  permissions; prompts are never logged.
- **Reviews:** two independent security reviews found no critical or high issues. Every medium
  and low finding was fixed with a regression test, except two lows, which are recorded as known
  limitations. Details are in SECURITY.md.

## Accessibility

- **Typeface:** Atkinson Hyperlegible, designed for low-vision readers.
- **Size and touch:** adjustable text size, 44 px targets (52 px for the elder), and a phone
  layout with a bottom tab bar.
- **Display settings:** high contrast and reduced motion.
- **Voice:** reading the day aloud and spoken questions, both of which only read or fill in text.
- **Testing:** axe scans in the end-to-end suite report zero serious or critical violations.

## Google Cloud

Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud SQL, Cloud Storage, Cloud
Scheduler (OIDC verified in code), Cloud Logging (structured JSON) and Vertex AI Gemini (service
account, no key) are all implemented in code and configuration. **Nothing has been deployed
yet.** Deployment needs a Google Cloud project with billing and the owner's approval.

## Verification

| Check | Result |
|---|---|
| Backend tests | 75 passing, 90% coverage |
| Frontend unit tests | 10 passing |
| End-to-end scenarios | 16 passing |
| Lint and types | ruff and mypy strict clean; TypeScript strict clean |
| Dependency audits | clean |
| PostgreSQL migrations | verified |
| Production container | verified |

The full record is in TESTING.md and AI_EVALUATION_CHECKLIST.md.
