# TraqConverter deployment

One supported path:

| Piece | Host | Root directory |
|---|---|---|
| Next.js frontend | Vercel | `traqconverter-frontend` |
| FastAPI API + queue worker | Railway | `backend` |
| Postgres + file storage | Supabase | - |

`backend/render.yaml` and `docker-compose.yml` also exist (see the end of this file), but Railway is the path this guide covers.

## 1. Supabase

1. Create a project at <https://supabase.com>. Save the database password.
2. **Project Settings → Database → Connection string**. Copy the **Transaction pooler** URL (port 6543) for the app, and the **Session pooler** or direct URL (port 5432) for migrations. Use the `postgresql+psycopg2://` scheme:

   ```
   postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
   ```

3. **Storage → New bucket**, name `traqconverter`, private.
4. **Project Settings → Storage → S3 connection → Generate new keys**. Copy the access key ID, secret, and endpoint (`https://<ref>.supabase.co/storage/v1/s3`) into `SUPABASE_S3_ACCESS_KEY`, `SUPABASE_S3_SECRET_KEY`, `SUPABASE_S3_ENDPOINT`.

## 2. Railway (backend)

1. **New Project → Deploy from GitHub repo**, root directory `backend`. `backend/railway.json` and `backend/nixpacks.toml` configure the build (Python deps, LibreOffice, Tesseract).
2. **Variables**: set every key from `backend/.env.example`. The ones that matter:

   | Variable | Value |
   |---|---|
   | `database_url` | Supabase transaction pooler URL |
   | `secret_key` | `python -c "import secrets;print(secrets.token_hex(32))"` |
   | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | provider keys |
   | `SUPABASE_S3_ENDPOINT`, `SUPABASE_S3_ACCESS_KEY`, `SUPABASE_S3_SECRET_KEY` | step 1.4 |
   | `S3_BUCKET_NAME` | `traqconverter` |
   | `stripe_secret_key`, `stripe_publishable_key`, `stripe_webhook_secret` | Stripe dashboard |
   | `STRIPE_PRICE_BASIC`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_CREDITS_10/25/50` | Stripe price IDs |
   | `STRIPE_PRICE_STUDIO`, `STRIPE_PRICE_AGENCY` | Optional Stripe price IDs (€79/month and €249/month). Unset: the plan shows "Contact us" |
   | `STRIPE_PORTAL_CONFIGURATION` | `bpc_...` printed by `python scripts/stripe_setup.py` |
   | `STRIPE_AUTOMATIC_TAX` | `false` (default). The seller, Lumax Digital LTD, is not VAT-registered, so checkout sends no `automatic_tax` or `tax_id_collection`; it still requires the billing address for invoices. Set `true` only after registering for VAT and enabling Stripe Tax |
   | `STRIPE_CONNECT_WEBHOOK_SECRET` | Signing secret of the Connect webhook (step 4) |
   | `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL` | `https://<vercel-domain>/success`, `/cancel` |
   | `FRONTEND_URL` | `https://<vercel-domain>`. Every link we send (password reset, invites, client links, Stripe return pages) starts with it; unset, they point at localhost |
   | `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | Resend key and a sender on a verified domain. Unset, no email is sent: no password resets, invites or payment notices |
   | `CORS_ORIGINS` | `https://<vercel-domain>` |

3. Deploy. `railway.json` runs `python -m alembic upgrade head` as the pre-deploy step, so every deploy migrates before the new version starts. A failed migration stops the deploy.
4. The queue worker runs inside the API process: `RUN_WORKER_INLINE=1` is the default, so one Railway service handles HTTP and translation jobs. To split them later, set `RUN_WORKER_INLINE=0` on the API and add a second service with start command `python -m app.workers.sqs_worker`.
5. Health check: `GET /health`.

### Migrations

The schema is one baseline migration (`d39e8a51bcaf`), so `python -m alembic upgrade head` works on an empty database. To run it by hand:

```bash
cd backend
source venv/bin/activate
export DATABASE_URL="postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
python -m alembic upgrade head
```

`alembic/env.py` reads `DATABASE_URL`, falling back to `database_url`.

## 3. Vercel (frontend)

1. **Add New → Project**, same repo, root directory `traqconverter-frontend`. `vercel.json` sets `npm ci` + `npm run build`.
2. Environment variable:

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | Railway API URL, no trailing slash |

   It is inlined at build time. A production build without it fails on purpose, so redeploy after changing it.
3. Deploy, then set `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, `FRONTEND_URL` and `CORS_ORIGINS` on Railway to the Vercel domain and redeploy the backend.

## 4. Stripe products, portal and webhooks

`scripts/stripe_setup.py` creates (or finds) the plan prices, the three credit-pack prices and the billing portal configuration, and prints the env vars to set. With `--with-webhooks` it also creates (or finds by URL) both webhook endpoints below on `https://api.onlinedoctranslator.ai`; new signing secrets go only to the `--secrets-out` file (mode 600), never to the terminal.

```bash
cd backend
STRIPE_SECRET_KEY=sk_live_... venv/bin/python scripts/stripe_setup.py --with-webhooks --dry-run
STRIPE_SECRET_KEY=sk_live_... venv/bin/python scripts/stripe_setup.py --with-webhooks --secrets-out ~/stripe-secrets.env
```

To set the webhooks up by hand instead: two endpoints, each with its own signing secret.

1. **Developers → Webhooks → Add endpoint**: `https://<railway-api>/stripe/webhook`, listening to events on **your account**.
   Events: `checkout.session.completed`, `invoice.payment_succeeded`, `customer.subscription.updated`, `customer.subscription.deleted`.
   Without `customer.subscription.updated`, plan changes made in the billing portal don't apply until the next renewal.
   Copy the signing secret (`whsec_...`) into `stripe_webhook_secret` on Railway.
2. **Add endpoint** again: `https://<railway-api>/stripe/connect/webhook`, listening to events on **connected accounts**.
   Events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `account.updated`, `account.application.deauthorized`.
   Without it, a client's card payment never unlocks their protected link.
   Copy its signing secret into `STRIPE_CONNECT_WEBHOOK_SECRET`.

## 5. Smoke test

1. Register, land on the dashboard.
2. Upload a small PDF at `/new-translation`; watch Railway logs for the job completing.
3. Open the project, approve segments, export PDF.
4. `/billing`: upgrade with test card `4242 4242 4242 4242`; the wallet should switch to Pro.

## Local development

```bash
# Backend (runs the worker in-process by default)
cd backend && source venv/bin/activate
python -m alembic upgrade head
uvicorn app.main:app --port 8000 --reload

# Frontend (falls back to http://127.0.0.1:8000 outside production builds)
cd traqconverter-frontend
npm ci
npm run dev
```

Or the whole stack in Docker: `docker compose up --build`. The `api` service migrates on start, `worker` runs the queue separately (`RUN_WORKER_INLINE=0` on `api`), and `web` serves the Next.js standalone build on port 3000. Needs `backend/.env`.

## Render (alternative)

`backend/render.yaml` defines a web service (migrations via `preDeployCommand`) and a separate `worker` service running `python -m app.workers.sqs_worker`. The web service sets `RUN_WORKER_INLINE=0` so jobs are only processed by the worker.

## Troubleshooting

**`InsufficientPrivilege: must be owner of table`** during migrations: connect as the `postgres` user and run

```sql
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO postgres', r.tablename);
  END LOOP;
END $$;
```

**Stripe signature errors**: `stripe_webhook_secret` must match that webhook's signing secret. Redeploy after changing it.

**Logo missing on the certification page**: upload it at `/settings/account` and check the object exists in the Supabase bucket.
