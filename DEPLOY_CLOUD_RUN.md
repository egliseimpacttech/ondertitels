## Deploy to Google Cloud Run

This repo is already set up for **Cloud Run** deployment via the included `Dockerfile`.

### 1) Prerequisites

- **gcloud** installed and authenticated
- A GCP project selected
- APIs enabled:
  - Cloud Run
  - Cloud Build
  - Artifact Registry
  - Firestore
  - IAM Credentials (needed for signed URL fallback)

Example:

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iamcredentials.googleapis.com
```

### 2) Create/choose a service account (recommended)

Cloud Run should run as a dedicated service account (not the default).

Roles typically needed:

- **Storage** for your bucket (uploads, job status persistence): `roles/storage.objectAdmin` (or stricter if you prefer)
- **Firestore** for church workspaces and memberships: `roles/datastore.user`
- **Signed URL fallback** (IAM signBlob): `roles/iam.serviceAccountTokenCreator` on the runtime service account
- **Firebase Admin invite endpoint** (`/api/admin/invite`): `roles/firebaseauth.admin` (only needed if you use the Admin screen)

Enable Firestore in Native mode in the same project (or configure the Firebase project used by the app). Church memberships and Stripe subscription state are stored there; the designated Ministère Apostolique Impact administrator is mapped directly from the verified `kaat.dbolle@gmail.com` account.

### 3) Create the GCS bucket (if you use large uploads)

Set `GCS_BUCKET_NAME` to an existing bucket, or create one:

```bash
gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=EU --uniform-bucket-level-access
```

### 4) Build & deploy to Cloud Run

From the repo root (`ondertitels/`):

```bash
gcloud run deploy ondertitels \
  --source . \
  --region europe-west1 \
  --set-build-env-vars VITE_FIREBASE_CONFIG_API_KEY=YOUR_FIREBASE_WEB_API_KEY \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars ENV=production \
  --set-env-vars FIREBASE_PROJECT_ID=YOUR_FIREBASE_PROJECT_ID \
  --set-env-vars GCS_BUCKET_NAME=YOUR_BUCKET_NAME \
  --set-env-vars ALLOWED_EMAILS="user1@example.com,user2@example.com" \
  --set-env-vars ADMIN_EMAILS="admin@example.com" \
  --set-env-vars ELEVENLABS_API_KEY="..." \
  --set-env-vars DEEPL_API_KEY="..." \
  --set-env-vars OPENAI_API_KEY="..." \
  --set-env-vars VOICE_ISOLATION_API_KEY="..."
```

Optional **translation** models (if omitted, the app uses [defaults in `backend/config.py`](backend/config.py)):

| Variable | Purpose |
|----------|---------|
| `OPENAI_TRANSLATION_MODEL` | Lingala + DeepL fallbacks (default `gpt-4o-mini`) |
| `OPENAI_TRANSLATION_MODEL_MG_KG_TS` | Malagasy, Kikongo, Tshiluba (default **`gpt-5.1-chat-latest`**, then `gpt-4.1`, then `gpt-4o` on errors). Legacy: `OPENAI_TRANSLATION_MODEL_KIKONGO`. |

They do **not** appear in the Cloud Run console until you set them. Add or update after the first deploy:

```bash
gcloud run services update ondertitels \
  --region europe-west1 \
  --update-env-vars OPENAI_TRANSLATION_MODEL=gpt-4o-mini,OPENAI_TRANSLATION_MODEL_MG_KG_TS=gpt-5.1-chat-latest
```

To see which models the running revision actually uses (no secrets), call **`GET /api/health`** after sign-in; the JSON includes `translation_models`.

Notes:

- **Do not commit** real keys to the repo. Prefer Cloud Run **Secrets** instead of `--set-env-vars` for API keys.
- If GCS is unavailable, the library falls back to tenant-scoped local disk storage for the current process. This is not a second backup: cloud-only files may be unavailable, and Cloud Run local disk is ephemeral. Large uploads use direct server upload while local fallback is active and remain subject to Cloud Run request limits.

### 5) Configure Stripe billing

Churches pay **€20/month, VAT included**, for a **100 GB** library quota. The `kaat.dbolle@gmail.com` workspace for Ministère Apostolique Impact is free and unlimited.

1. Enable Stripe Tax and configure your tax registrations in Stripe. Checkout uses an inclusive EUR price and Stripe automatic tax.
2. Store the Stripe secret key and webhook signing secret in Secret Manager, then expose them to Cloud Run as `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`. Set `APP_BASE_URL` to the public HTTPS Cloud Run URL.
3. Configure a webhook at `https://YOUR_CLOUD_RUN_URL/api/billing/webhook` for `checkout.session.completed` and `customer.subscription.created`, `customer.subscription.updated`, and `customer.subscription.deleted`.
4. Ensure the Firebase Authentication project allows email/password sign-up. Church administrators invite members from the in-app Administration page.

Example (after adding the secrets to Secret Manager):

```bash
gcloud run services update ondertitels \
  --region europe-west1 \
  --update-secrets STRIPE_SECRET_KEY=stripe-secret:latest,STRIPE_WEBHOOK_SECRET=stripe-webhook-secret:latest \
  --update-env-vars APP_BASE_URL=https://YOUR_CLOUD_RUN_URL
```

The app is also a PWA. Serve it over HTTPS and install it from the desktop browser's **Install app** action; no separate native installer is produced.

### 6) Verify

- App: open the Cloud Run URL
- Health:
  - `GET /health`
  - `GET /api/health` (requires Firebase auth header; frontend does this automatically after sign-in)

