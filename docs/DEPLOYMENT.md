# Deployment

## Live deployment: Vercel + Supabase (current)

Production: https://eldercare-steel-kappa.vercel.app

| Part | Setup |
|---|---|
| Frontend | Vite build served from Vercel's CDN (`vercel.json`: `buildCommand`, `outputDirectory`, SPA rewrite, one-year immutable cache for `/assets/*`) |
| API | `api/index.py` (Vercel Python function in `bom1`) imports `backend/app`; `includeFiles` bundles the backend and PDF fonts; `requirements.txt` holds only the slim core dependencies |
| Database | Supabase PostgreSQL (Mumbai), dedicated role and `eldercare` schema (not exposed to Supabase's auto-API), transaction pooler on port 6543, `DB_POOL=null` |
| Documents | `STORAGE_BACKEND=db` (bytes in `document_blobs`) |
| Reminders | Supabase `pg_cron` + `pg_net` POST `/internal/jobs/tick` every 5 minutes with `X-Job-Token`; a daily Vercel Cron (`CRON_SECRET`) is a backstop, because the Hobby plan allows only daily crons |
| Migrations | Run from a workstation: `DATABASE_URL=<session pooler, port 5432> uv run alembic upgrade head` |
| Redeploy | `vercel deploy --prod --scope be-tu-x` (or push to `main` if Git is connected) |

Environment variables (set in the Vercel project): `ENVIRONMENT`, `APP_BASE_URL`, `DATABASE_URL`, `DB_POOL`,
`SECRET_KEY`, `CRON_SECRET`, `JOB_TRIGGER_TOKEN`, `STORAGE_BACKEND`, `EMAIL_TRANSPORT`, `AI_PROVIDER`.
See ENVIRONMENT_VARIABLES.md for meanings.

# Deployment: Google Cloud Run (alternative)

**Status: not deployed yet.** Everything below is ready to run. It needs a Google Cloud project
with billing enabled, the `gcloud` CLI, and your approval, because the commands create billable
resources. Cloud SQL is the main cost, at roughly US$10 or more a month for the smallest
instance. Any PostgreSQL provider also works through `DATABASE_URL`.

## Google services used

| Service | Use |
|---|---|
| Cloud Run | Hosts the single container (API and SPA), scales to zero |
| Cloud Build | `cloudbuild.yaml`: tests, image build, migration job, deploy |
| Artifact Registry | Container images |
| Secret Manager | `DATABASE_URL`, `SECRET_KEY`, `SMTP_PASSWORD` mounted as environment variables |
| Cloud SQL (PostgreSQL) | Primary database, with automated backups and point-in-time recovery |
| Cloud Storage | Private bucket for medical documents (uniform access, versioning) |
| Cloud Scheduler | Calls `/internal/jobs/tick` every 5 minutes with an OIDC token |
| Vertex AI (Gemini) | Assistant answers, authenticated with the Cloud Run service account |
| Cloud Logging and Monitoring | Structured JSON logs with trace correlation; uptime check on `/readyz` |

## One-time setup

```bash
PROJECT=your-project REGION=europe-west2
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com sqladmin.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com
gcloud artifacts repositories create eldercare --repository-format=docker --location=$REGION

# Database
gcloud sql instances create eldercare-db --database-version=POSTGRES_17 --tier=db-f1-micro \
  --region=$REGION --backup-start-time=03:00 --enable-point-in-time-recovery
gcloud sql databases create eldercare --instance=eldercare-db
gcloud sql users create eldercare --instance=eldercare-db --password="$(openssl rand -base64 24)"

# Documents bucket (private)
gcloud storage buckets create gs://$PROJECT-eldercare-docs --location=$REGION \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$PROJECT-eldercare-docs --versioning

# Service accounts
gcloud iam service-accounts create eldercare-run
gcloud iam service-accounts create eldercare-scheduler
RUN_SA=eldercare-run@$PROJECT.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$RUN_SA --role=roles/cloudsql.client
gcloud storage buckets add-iam-policy-binding gs://$PROJECT-eldercare-docs --member=serviceAccount:$RUN_SA --role=roles/storage.objectAdmin

# Secrets (values typed by you, never committed)
printf '%s' "postgresql+psycopg://eldercare:PASSWORD@/eldercare?host=/cloudsql/$PROJECT:$REGION:eldercare-db" \
  | gcloud secrets create eldercare-database-url --data-file=-
python -c "import secrets;print(secrets.token_urlsafe(48),end='')" | gcloud secrets create eldercare-secret-key --data-file=-
printf '%s' "YOUR_SMTP_APP_PASSWORD" | gcloud secrets create eldercare-smtp-password --data-file=-
for s in eldercare-database-url eldercare-secret-key eldercare-smtp-password; do
  gcloud secrets add-iam-policy-binding $s --member=serviceAccount:$RUN_SA --role=roles/secretmanager.secretAccessor
done
```

Edit `deploy/cloudrun.env.yaml` (the `CHANGE_ME` values) and add
`--add-cloudsql-instances $PROJECT:$REGION:eldercare-db` to the deploy and migrate steps in
`cloudbuild.yaml`.

### Assistant on Vertex AI (optional, recommended)

```bash
gcloud services enable aiplatform.googleapis.com
gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$RUN_SA --role=roles/aiplatform.user
```

Add `AI_PROVIDER: vertex`, `VERTEX_LOCATION: $REGION` and optionally `AI_MODEL` to
`deploy/cloudrun.env.yaml`. Without them the assistant runs in offline record-lookup mode and
says so in the UI.

## Build and deploy

```bash
gcloud builds submit --config cloudbuild.yaml --substitutions=_REGION=$REGION,SHORT_SHA=$(git rev-parse --short HEAD)
```

This runs the backend and frontend checks, builds and pushes the image, runs `alembic upgrade
head` as a Cloud Run job, and deploys the service.

## Scheduler

```bash
URL=$(gcloud run services describe eldercare --region $REGION --format='value(status.url)')
gcloud scheduler jobs create http eldercare-tick --location=$REGION --schedule="*/5 * * * *" \
  --uri="$URL/internal/jobs/tick" --http-method=POST \
  --oidc-service-account-email=eldercare-scheduler@$PROJECT.iam.gserviceaccount.com \
  --oidc-token-audience="$URL/internal/jobs/tick"
```

Set `APP_BASE_URL=$URL` and `JOBS_OIDC_AUDIENCE=$URL/internal/jobs/tick` in
`deploy/cloudrun.env.yaml`, then redeploy.

## Verify after deploying

1. `curl $URL/readyz` returns `{"status":"ok"}`. This runs a real database query.
2. Open `$URL` in a private window, register, create a profile and add a medicine.
3. `gcloud scheduler jobs run eldercare-tick --location=$REGION`, then check Cloud Logging for
   `reminder tick complete`.
4. Create an uptime check in Cloud Monitoring on `/readyz`, with an alert to the operator email.

## Optional: Vercel for the frontend

The supported production topology is a single Cloud Run origin. If the frontend must be hosted
on Vercel, deploy `frontend/` as a static Vite site with a rewrite of `/api/*` to the Cloud Run
URL, so that cookies stay first-party from the browser's point of view. A Vercel deployment is
not a Cloud Run deployment, and should not be presented as one in the hackathon submission.
