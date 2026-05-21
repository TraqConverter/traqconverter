# TraqConverter — Deployment Guide

This file is the minimum set of steps to get TraqConverter running in
production from a fresh clone. The two halves are independent: you can
deploy the FastAPI backend on one host and the Next.js frontend on
another, or use the bundled `docker-compose.yml` to run everything
locally.

---

## 1. Prerequisites

- Python 3.11
- Node.js 20
- PostgreSQL 14+
- A Stripe account with two recurring prices (one for Basic, one for Pro) and
  one webhook endpoint configured for the events
  `checkout.session.completed`, `invoice.payment_succeeded`,
  `customer.subscription.deleted`
- An OpenAI API key
- (Optional) AWS S3 bucket + SQS queue if you're running the queue worker
  in production. For local dev you can skip this — the watchdog disables
  itself if `SQS_QUEUE_URL` is empty.

---

## 2. Backend — environment variables

Copy `backend/.env.example` to `backend/.env` and fill in real values.
Every key is documented in the example file. The required ones:

| Key                          | Notes                                                      |
| ---------------------------- | ---------------------------------------------------------- |
| `database_url`               | `postgresql+psycopg2://user:pass@host:5432/db`             |
| `secret_key`                 | 32+ bytes (`openssl rand -hex 32`)                         |
| `OPENAI_API_KEY`             | from platform.openai.com                                   |
| `stripe_secret_key`          | `sk_live_...` (or `sk_test_...` for testing)               |
| `stripe_publishable_key`     | `pk_live_...`                                              |
| `stripe_webhook_secret`      | `whsec_...` (from your Stripe webhook endpoint)            |
| `STRIPE_PRICE_PRO`           | the recurring price ID for Pro                             |
| `STRIPE_PRICE_BASIC`         | the recurring price ID for Basic (optional)                |
| `STRIPE_SUCCESS_URL`         | absolute URL of your `/success` page                       |
| `STRIPE_CANCEL_URL`          | absolute URL of your `/cancel` page                        |
| `S3_BUCKET_NAME`             | bucket holding uploads + rebuilt translations              |
| `CORS_ORIGINS`               | comma-separated list of frontend origins (no `*` in prod)  |

Optional but recommended:

| Key                            | Notes                                                |
| ------------------------------ | ---------------------------------------------------- |
| `SENTRY_DSN`                   | enables Sentry error tracking at startup             |
| `SENTRY_TRACES_SAMPLE_RATE`    | float between 0 and 1, default `0.1`                 |
| `TESSERACT_CMD`                | only on Windows or non-default Tesseract installs    |

---

## 3. Backend — first deploy

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head            # run migrations
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The FastAPI server is now reachable at `http://localhost:8000`. The
`/health` endpoint should return `{"status": "ok"}` and `/health/ready`
should return `{"status": "ready"}`.

Configure your Stripe webhook to forward to:

```
POST  https://<your-api-host>/stripe/webhook
```

For local Stripe testing, run the CLI relay:

```bash
stripe listen --forward-to localhost:8000/stripe/webhook
```

---

## 4. Frontend — environment variables

In `traqconverter-frontend/.env.local`:

```
NEXT_PUBLIC_API_URL=https://<your-api-host>
```

---

## 5. Frontend — build & run

```bash
cd traqconverter-frontend
npm ci
npm run build
npm run start
```

The SPA is now reachable at `http://localhost:3000`.

---

## 6. Docker — single-command stack

The repo ships a `docker-compose.yml` that wires together Postgres, the
API, the queue worker, and the Next.js frontend.

```bash
docker compose up -d --build
docker compose run --rm api alembic upgrade head
```

Containers:

- `db` — Postgres 16
- `api` — FastAPI on port 8000, health-checked
- `worker` — queue worker (same image, different `CMD`)
- `web`   — Next.js standalone server on port 3000

Logs:

```bash
docker compose logs -f api
docker compose logs -f worker
```

---

## 7. CI

`.github/workflows/ci.yml` runs on every push and pull request:

- **backend**: ruff + ast.parse syntax check + smoke-import of `app.main`
- **frontend**: `tsc --noEmit` + `next build`

CI passing is a hard prerequisite for merging into `main`.

---

## 8. Production hardening

These are already wired up — listing here so you know what to expect:

- **CORS** is env-driven via `CORS_ORIGINS`. Lock down to your real
  frontend domain in production (no `*`).
- **Security headers** (`X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, plus `Strict-Transport-Security` when
  `environment=production`) are set in middleware.
- **Auth rate limiting** is on `/auth/login` (10 req / 60 s / IP) and
  `/auth/register` (5 req / 5 min / IP). Replace the in-memory bucket
  with Redis if you scale to multiple API instances.
- **JWT revocation** ships out of the box: changing a password bumps
  `users.token_version`, instantly invalidating every older token.
- **WebSocket auth**: pass `?token=<jwt>` to `/ws/projects` and
  `/ws/projects/{id}`. Project-channel sockets are checked against the
  caller's team membership before `accept()`.
- **Watchdog**: started automatically at app boot. Disabled when
  `SQS_QUEUE_URL` is empty so dev environments don't spam logs with
  AWS errors.
- **Health checks**: `/health` (liveness, fast) and `/health/ready`
  (readiness — pings the DB).

---

## 9. Operational notes

- Migrations live in `backend/alembic/versions/`. Run
  `alembic upgrade head` on every deploy. CI validates that the
  revision graph has a single head before allowing a merge.
- The queue worker writes scratch files to `uploads/`. Mount this as a
  volume (compose does this automatically) or it'll grow unbounded
  inside the container.
- `app/services/layout_translator.py` rebuilds the source-resembling
  output file on every successful translation. It uses PyMuPDF (PDF),
  python-docx (DOCX), or PIL+Tesseract (images) — make sure
  `tesseract` is installed in the container (the bundled `Dockerfile`
  installs it).
- Default subscription credit grants are `BASIC=19`,  `PRO=29` —
  edit `app/core/plan_features.py::SUBSCRIPTION_GRANTS` if you change
  pricing.

---

## 10. Quick verification after deploy

```bash
# Liveness
curl https://<api>/health
# Readiness (also checks DB)
curl https://<api>/health/ready

# Stripe webhook signing secret matches
stripe trigger checkout.session.completed --override checkout_session:metadata.user_id=<test-user-id> --override checkout_session:metadata.team_id=<test-team-id> --override checkout_session:metadata.plan=PRO
# → backend log should show "sub_checkout_..." StripeEvent inserted
```
