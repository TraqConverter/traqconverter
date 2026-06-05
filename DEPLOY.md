# TraqConverter — Deployment Guide

Production stack:

- **Vercel** → Next.js frontend
- **Supabase** → Postgres database + S3-compatible object storage
- **Railway** (or **Render**) → FastAPI API + translation worker

Total wall-clock time for a fresh deploy is about 45 minutes.

## 1. Create the Supabase project

1. Sign in at <https://supabase.com> and click **New project**. Pick a
   region close to your users.
2. Save the **database password** when prompted — you'll need it.
3. After provisioning finishes (~2 minutes), go to **Project Settings → Database → Connection string** and copy the **"Transaction" pooler URL** (port 6543). It looks like:

   ```
   postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
   ```

   That's your `database_url`.
4. Go to **Storage** and click **New bucket**. Name it `traqconverter`. Leave it as private.
5. Go to **Project Settings → Storage → S3 connection** and click
   **Generate new keys**. Copy:
   - **Access key ID**
   - **Secret access key**
   - **Endpoint** (looks like `https://<ref>.supabase.co/storage/v1/s3`)

   Those map to `SUPABASE_S3_ACCESS_KEY`, `SUPABASE_S3_SECRET_KEY`,
   `SUPABASE_S3_ENDPOINT`.

## 2. Apply database migrations against Supabase

From your local machine:

```bash
cd backend
.\venv\Scripts\activate   # or `source venv/bin/activate` on macOS/Linux

# Point alembic at the Supabase DB
export DATABASE_URL="postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres"

python -m alembic upgrade head
```

You should see the migration chain run cleanly, ending with
`d39e8a51bcaf` (the Postgres job-queue table). The migration order
expected by alembic:

```
b34ab420b451 → … → c427fe1382bd → d39e8a51bcaf (head)
```

## 3. Deploy the backend on Railway

1. Sign in at <https://railway.app> and click **New Project →
   Deploy from GitHub repo**. Pick the repo, leave the root as
   `backend/`. Railway auto-detects Python.
2. Open the project → **Settings → Variables** and paste in every
   key from `backend/.env.example`. The important ones:

   | Variable | Value |
   |---|---|
   | `database_url` | Supabase pooler URL from step 1 |
   | `secret_key` | `python -c "import secrets;print(secrets.token_hex(32))"` |
   | `OPENAI_API_KEY` | from OpenAI dashboard |
   | `ANTHROPIC_API_KEY` | from Anthropic console |
   | `SUPABASE_S3_ENDPOINT` | from step 1.5 |
   | `SUPABASE_S3_ACCESS_KEY` | from step 1.5 |
   | `SUPABASE_S3_SECRET_KEY` | from step 1.5 |
   | `S3_BUCKET_NAME` | `traqconverter` |
   | `stripe_secret_key` | live Stripe key |
   | `stripe_publishable_key` | live Stripe key |
   | `stripe_webhook_secret` | from Stripe dashboard once webhook is created |
   | `STRIPE_PRICE_PRO`, `STRIPE_PRICE_BASIC` | Stripe price IDs |
   | `STRIPE_PRICE_CREDITS_10/25/50` | Stripe price IDs |
   | `STRIPE_SUCCESS_URL` | `https://<your-vercel-domain>/success` |
   | `STRIPE_CANCEL_URL` | `https://<your-vercel-domain>/cancel` |
   | `CORS_ORIGINS` | `https://<your-vercel-domain>` |

3. Add a **second service** in the same Railway project for the worker:
   - Service type: **Empty service** (or fork the existing one)
   - **Start command:** `python -m app.workers.sqs_worker`
   - Same env vars as the API.
   - You don't need a public domain for the worker.

4. Wait for both deploys to finish. The API service's public URL
   (e.g. `https://traqconverter-api.up.railway.app`) is what the
   frontend will call.

## 4. Deploy the frontend on Vercel

1. Sign in at <https://vercel.com> and click **Add New → Project**.
   Point it at the same GitHub repo and set the **root directory** to
   `traqconverter-frontend/`. Vercel auto-detects Next.js.
2. Add environment variables (Vercel dashboard → Project → Settings → Environment Variables):

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://traqconverter-api.up.railway.app` (your Railway API URL, no trailing slash) |
   | `NEXT_PUBLIC_WS_URL` | `wss://traqconverter-api.up.railway.app` |

3. Click **Deploy**. Once live, copy the production URL (e.g.
   `https://traqconverter.vercel.app`) and update **Railway** env
   vars `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, and
   `CORS_ORIGINS` to point at it. Trigger a redeploy on Railway so
   the new CORS rule takes effect.

## 5. Stripe webhook

1. Stripe dashboard → **Developers → Webhooks → Add endpoint**.
2. Endpoint URL: `https://traqconverter-api.up.railway.app/stripe/webhook`
3. Events to send (at minimum):
   - `checkout.session.completed`
   - `invoice.payment_succeeded`
   - `customer.subscription.deleted`
4. After creating, click into the webhook and copy the **Signing
   secret** (starts with `whsec_`). Paste it as
   `stripe_webhook_secret` in Railway.

## 6. Smoke test

Visit your Vercel URL:

1. Register a new account → you should land on the dashboard.
2. Upload a small test PDF or image at `/new-translation`.
3. Watch the worker logs in Railway:
   ```
   📥 Processing job=… project=…
   Storage backend: Supabase Storage (S3-compatible)
   Object download successful: …
   N segments created
   ✅ Completed job=…
   ```
4. Open the project in `/jobs`, approve segments, export PDF.
5. Visit `/billing` and try an upgrade with Stripe test card
   `4242 4242 4242 4242`. Confirm the wallet flips to Pro.

## 7. Local development (still works)

For local dev you don't need any of the above:

```bash
# Backend
cd backend
.\venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Worker (separate terminal)
python -m app.workers.sqs_worker

# Frontend (separate terminal)
cd traqconverter-frontend
npm run dev
```

Point your local `backend/.env` at either a local Postgres or your
Supabase pooler URL — the code is identical.

## What changed vs. the AWS deployment

| Was | Now |
|---|---|
| AWS S3 | Supabase Storage (S3-compatible API) |
| AWS SQS | Postgres `translation_jobs` table + `FOR UPDATE SKIP LOCKED` worker |
| AWS RDS / external Postgres | Supabase Postgres |
| EC2 / ECS for backend | Railway (or Render / Fly.io) |
| Self-hosted Next.js | Vercel |
| Manual rotation of AWS access keys | Supabase service keys + Vercel/Railway env vars |
| boto3 → S3 with IAM | boto3 → Supabase endpoint with service keys |
| Watchdog re-enqueued via SQS SendMessage | Watchdog resets `processing → pending` directly in Postgres |

Code is backend-agnostic — leaving `SUPABASE_S3_ENDPOINT` blank falls
back to real AWS S3 so you can A/B test or fall back without code
changes.

## Troubleshooting

**`apply_redactions failed`**: Old PyMuPDF. Railway uses 1.24.13 from
requirements.txt; if you see this, force a clean rebuild.

**Worker doesn't pick up jobs**: Verify the `translation_jobs` table
exists in Supabase. If `python -m alembic upgrade head` didn't run,
re-run it pointed at the Supabase URL.

**`InsufficientPrivilege: must be owner of table`** when running
alembic: Connect to Supabase as the `postgres` superuser and run:
```sql
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO postgres', r.tablename);
  END LOOP;
END $$;
```

**Stripe webhook signature errors**: The `stripe_webhook_secret` env
var must match the secret shown in Stripe dashboard → that specific
webhook's "Signing secret". Restart Railway after updating.

**Logo not appearing on cert page**: User must upload via
`/settings/account → Branding`. Confirm the row in Supabase Storage:
the file should be at `uploads/<uuid>_<filename>` and visible in the
bucket browser.
