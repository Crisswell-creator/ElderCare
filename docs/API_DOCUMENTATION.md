# API documentation

Generated from the live OpenAPI schema (`uv run python -m scripts.gen_api_docs` regenerates it).
Interactive docs are served at `/api/docs` outside production.

All endpoints return JSON. Errors use one envelope: `{"error": {"code", "message", "fields"?}}`.
State-changing requests need the `X-CSRF-Token` header (copy of the `ec_csrf` cookie).
Patient-scoped routes return **404** when the caller is not an active member of that care circle,
and **403** when they are a member without the required permission.


## Appointments

| Method | Path | Purpose |
|---|---|---|
| DELETE | `/api/patients/{patient_id}/questions/{qid}` | Delete Question |
| GET | `/api/patients/{patient_id}/appointments` | List Appointments |
| GET | `/api/patients/{patient_id}/appointments/{appt_id}/calendar.ics` | Appointment Ics |
| GET | `/api/patients/{patient_id}/questions` | List Questions |
| POST | `/api/patients/{patient_id}/appointments` | Create Appointment |
| POST | `/api/patients/{patient_id}/appointments/{appt_id}/cancel` | Cancel Appointment |
| POST | `/api/patients/{patient_id}/appointments/{appt_id}/complete` | Complete Appointment |
| POST | `/api/patients/{patient_id}/questions` | Add Question |
| POST | `/api/patients/{patient_id}/questions/{qid}/resolve` | Resolve Question |
| PUT | `/api/patients/{patient_id}/appointments/{appt_id}` | Update Appointment |

## Assistant

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/patients/{patient_id}/assistant` | Info |
| POST | `/api/patients/{patient_id}/assistant` | Ask |

## Auth

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/auth/memberships` | My Memberships |
| GET | `/api/auth/session` | Session Info |
| PATCH | `/api/auth/me` | Update Me |
| POST | `/api/auth/change-password` | Change Password |
| POST | `/api/auth/forgot-password` | Forgot Password |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/logout` | Logout |
| POST | `/api/auth/register` | Register |
| POST | `/api/auth/resend-verification` | Resend Verification |
| POST | `/api/auth/reset-password` | Reset Password |
| POST | `/api/auth/verify-email` | Verify Email |

## Care Team

| Method | Path | Purpose |
|---|---|---|
| DELETE | `/api/patients/{patient_id}/invitations/{invitation_id}` | Revoke Invitation |
| DELETE | `/api/patients/{patient_id}/members/{member_id}` | Revoke Member |
| GET | `/api/access-requests/mine` | My Requests |
| GET | `/api/patients/{patient_id}/access-requests` | List Requests |
| GET | `/api/patients/{patient_id}/invitations` | List Invitations |
| GET | `/api/patients/{patient_id}/members` | List Members |
| PATCH | `/api/patients/{patient_id}/members/{member_id}` | Update Member |
| POST | `/api/access-requests/{request_id}/withdraw` | Withdraw Request |
| POST | `/api/invitations/redeem` | Redeem Invitation |
| POST | `/api/patients/{patient_id}/access-requests/{request_id}/decision` | Decide Request |
| POST | `/api/patients/{patient_id}/invitations` | Create Invitation |
| PUT | `/api/patients/{patient_id}/members/me/preferences` | Set Preferences |

## Collaboration

| Method | Path | Purpose |
|---|---|---|
| DELETE | `/api/patients/{patient_id}/notes/{note_id}` | Delete Note |
| GET | `/api/patients/{patient_id}/help-alerts/latest` | Help Alert Status |
| GET | `/api/patients/{patient_id}/notes` | List Notes |
| GET | `/api/patients/{patient_id}/tasks` | List Tasks |
| POST | `/api/patients/{patient_id}/help-alerts` | Send Help Alert |
| POST | `/api/patients/{patient_id}/notes` | Create Note |
| POST | `/api/patients/{patient_id}/tasks` | Create Task |
| POST | `/api/patients/{patient_id}/tasks/{task_id}/status` | Set Task Status |
| PUT | `/api/patients/{patient_id}/notes/{note_id}` | Update Note |
| PUT | `/api/patients/{patient_id}/tasks/{task_id}` | Update Task |

## Documents

| Method | Path | Purpose |
|---|---|---|
| DELETE | `/api/patients/{patient_id}/documents/{doc_id}` | Delete Document |
| GET | `/api/patients/{patient_id}/documents` | List Documents |
| GET | `/api/patients/{patient_id}/documents/{doc_id}/download` | Download Document |
| POST | `/api/patients/{patient_id}/documents` | Upload Document |

## Insights

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/me/overview` | My Overview |
| GET | `/api/patients/{patient_id}/activity` | Activity |
| GET | `/api/patients/{patient_id}/adherence` | Adherence Report |
| GET | `/api/patients/{patient_id}/overview` | Overview |
| GET | `/api/patients/{patient_id}/visit-summary.pdf` | Visit Summary |

## Medications

| Method | Path | Purpose |
|---|---|---|
| DELETE | `/api/patients/{patient_id}/medications/{med_id}` | Remove Medication |
| GET | `/api/patients/{patient_id}/doses` | List Doses |
| GET | `/api/patients/{patient_id}/medications` | List Medications |
| GET | `/api/patients/{patient_id}/medications/{med_id}` | Get Medication |
| POST | `/api/patients/{patient_id}/doses/{dose_id}/skip` | Skip Dose |
| POST | `/api/patients/{patient_id}/doses/{dose_id}/snooze` | Snooze Dose |
| POST | `/api/patients/{patient_id}/doses/{dose_id}/take` | Take Dose |
| POST | `/api/patients/{patient_id}/doses/{dose_id}/undo` | Undo Dose |
| POST | `/api/patients/{patient_id}/medications` | Create Medication |
| POST | `/api/patients/{patient_id}/medications/{med_id}/as-needed` | Record As Needed |
| POST | `/api/patients/{patient_id}/medications/{med_id}/inventory` | Record Inventory |
| POST | `/api/patients/{patient_id}/medications/{med_id}/status` | Set Medication Status |
| PUT | `/api/patients/{patient_id}/medications/{med_id}` | Update Medication |

## Notifications

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/notifications` | List Notifications |
| POST | `/api/notifications/read-all` | Mark All Read |
| POST | `/api/notifications/{notification_id}/read` | Mark Read |

## Patients

| Method | Path | Purpose |
|---|---|---|
| DELETE | `/api/patients/{patient_id}/allergies/{item_id}` | Delete Allergies |
| DELETE | `/api/patients/{patient_id}/contacts/{item_id}` | Delete Contacts |
| DELETE | `/api/patients/{patient_id}/doctors/{item_id}` | Delete Doctors |
| DELETE | `/api/patients/{patient_id}/history/{item_id}` | Delete History |
| GET | `/api/patients/{patient_id}` | Get Patient |
| GET | `/api/patients/{patient_id}/emergency` | Emergency Info |
| PATCH | `/api/patients/{patient_id}` | Update Patient |
| POST | `/api/patients` | Create Patient |
| POST | `/api/patients/{patient_id}/allergies` | Create Allergies |
| POST | `/api/patients/{patient_id}/contacts` | Create Contacts |
| POST | `/api/patients/{patient_id}/doctors` | Create Doctors |
| POST | `/api/patients/{patient_id}/history` | Create History |
| PUT | `/api/patients/{patient_id}/allergies/{item_id}` | Update Allergies |
| PUT | `/api/patients/{patient_id}/contacts/{item_id}` | Update Contacts |
| PUT | `/api/patients/{patient_id}/doctors/{item_id}` | Update Doctors |
| PUT | `/api/patients/{patient_id}/history/{item_id}` | Update History |
| PUT | `/api/patients/{patient_id}/reminder-rules` | Set Reminder Rules |

## Reports

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/patients/{patient_id}/reports` | Summary |
| GET | `/api/patients/{patient_id}/reports/appointments.csv` | Appointments Csv |
| GET | `/api/patients/{patient_id}/reports/doses.csv` | Doses Csv |
| GET | `/api/patients/{patient_id}/reports/tasks.csv` | Tasks Csv |

## Internal

| Method | Path | Purpose |
|---|---|---|
| POST | `/internal/jobs/tick` | Reminder tick: Google OIDC (Cloud Scheduler) or `X-Job-Token`. |
| GET | `/healthz` | Liveness |
| GET | `/readyz` | Readiness: runs `SELECT 1` against the database |
