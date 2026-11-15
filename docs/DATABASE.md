# Database

The database is PostgreSQL in production and SQLite for local development and tests. The schema
is defined in `backend/app/models.py` and versioned with Alembic in `backend/alembic/versions`.

## Migrations

```bash
cd backend
uv run alembic upgrade head        # apply
uv run alembic downgrade base      # roll back everything
uv run alembic check               # fails if models and migrations drift
uv run alembic revision --autogenerate -m "describe change"
```

| Revision | Change |
|---|---|
| 0001 | Initial schema, plus append-only triggers on `audit_events` (PL/pgSQL on PostgreSQL, `RAISE(ABORT)` on SQLite) |
| 0002 | `medications.schedule_anchor_at`, with a server default so existing rows migrate safely |
| 0003 | `care_tasks`, `care_notes`, `users.preferences` (JSON), `emergency_contacts.priority`, all with server defaults; verified on SQLite and PostgreSQL 17 |

Verified: upgrade, downgrade and upgrade again on SQLite; `alembic check` reports no drift; the
test suite runs against the migrated schema rather than `create_all`. See TESTING.md for the
PostgreSQL run.

## Tables

| Table | Purpose | Notable constraints and indexes |
|---|---|---|
| users | Accounts (argon2id hashes) | unique email |
| user_sessions | Server-side sessions (HMAC of token) | unique token_hash, index user_id |
| auth_tokens | Single-use email verification and reset tokens | unique token_hash |
| auth_attempts | Throttling log | index (key, created_at) |
| patients | Elder profile and reminder rules | |
| memberships | Care circle: role, permissions (JSON), representative flag, email preferences | unique (patient_id, user_id) |
| invitations | Hashed, expiring, single-use codes | unique code_hash |
| access_requests | Pending, approved, rejected or withdrawn requests | index patient_id |
| allergies, history_entries, emergency_contacts, doctors | Structured health record | index patient_id |
| medications | Medicine, schedule type, status, cached stock | index (patient_id, status) |
| medication_times | Local time and weekday bitmask | unique (medication_id, local_time) |
| inventory_events | Append-style stock ledger | index medication_id |
| dose_events | One row per scheduled or as-needed dose | unique (medication_id, scheduled_at); index (patient_id, scheduled_at); index (status, scheduled_at) |
| appointments | Visits and reminder offsets | index (patient_id, starts_at) |
| visit_questions | Questions for the doctor | index patient_id |
| documents | Metadata. Bytes live in private storage. | unique storage_key |
| notifications | Outbox and in-app notification centre | unique dedupe_key; index (status, next_attempt_at); index (recipient_user_id, created_at) |
| care_tasks | Coordination tasks | index (patient_id, status, due_date); index assignee_user_id |
| care_notes | Shared notes (4 kinds) | index (patient_id, created_at) |
| audit_events | Activity history (append-only) | index (patient_id, created_at); UPDATE and DELETE rejected by trigger |

## Query efficiency

- **Dashboards make one request.** `/overview` returns everything the screen needs, trimmed to
  the caller's permissions.
- **The multi-patient caregiver home avoids N+1 queries.** It uses a fixed number of grouped
  queries regardless of how many patients the caregiver supports.
- **Lists use keyset pagination.** The activity history and notifications page by id, which is
  stable under concurrent inserts.
- **Dose generation uses bulk lookups.** It reads existing doses for all medicines in one query
  per tick and inserts only the missing rows.
- **Relationships load eagerly by default.** `joined` or `selectin` loading prevents lazy-load
  loops when serialising.

## Backups and recovery

On Cloud SQL, enable automated daily backups and point-in-time recovery (7-day log retention).
Restore by creating a clone at a timestamp and pointing `DATABASE_URL`, held in Secret Manager,
at it. Documents live in a GCS bucket with object versioning enabled. The audit log is append-only,
so a restore never loses history that was acknowledged before the backup point.
