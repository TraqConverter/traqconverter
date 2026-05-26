import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pathlib import Path

from app.core.logging_config import configure_logging

# ----------------------------------------------------
# Load environment variables
# ----------------------------------------------------
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# ----------------------------------------------------
# Configure logging
# ----------------------------------------------------
configure_logging()

logger = logging.getLogger(__name__)
logger.info("Starting TraqConverter API")

# Startup diagnostic — log whether LibreOffice is available on PATH
# so we can tell at a glance whether the nixpacks.toml install
# landed. Without it, the PDF export silently falls back to the
# ReportLab pipeline (which doesn't match the DOCX visually).
def _log_libreoffice_status():
    import shutil
    for binname in ("soffice", "libreoffice"):
        path = shutil.which(binname)
        if path:
            logger.info(
                "✅ LibreOffice available for DOCX→PDF: %s -> %s",
                binname,
                path,
            )
            return
    logger.warning(
        "⚠️  LibreOffice NOT on PATH — PDF export will fall back to "
        "ReportLab (PDF will visually drift from DOCX). Add "
        "`libreoffice` + `libreoffice-writer` to the apt-get install "
        "line in backend/Dockerfile (or nixpacks.toml aptPkgs if "
        "using Nixpacks)."
    )


_log_libreoffice_status()

# ----------------------------------------------------
# Sentry (optional — enabled when SENTRY_DSN is set)
# ----------------------------------------------------
try:
    from app.config import settings as _bootstrap_settings

    if getattr(_bootstrap_settings, "SENTRY_DSN", None):
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=_bootstrap_settings.SENTRY_DSN,
            traces_sample_rate=_bootstrap_settings.SENTRY_TRACES_SAMPLE_RATE,
            environment=_bootstrap_settings.environment,
            integrations=[FastApiIntegration()],
        )
        logger.info(
            "Sentry initialised (env=%s)", _bootstrap_settings.environment
        )
except Exception as _e:
    # Never let observability breakage take the app down.
    logger.warning("Sentry init skipped: %s", _e)

# ----------------------------------------------------
# Create FastAPI app
# ----------------------------------------------------
app = FastAPI()

# ----------------------------------------------------
# CORS — env-driven via CORS_ORIGINS (audit medium fix).
# ----------------------------------------------------
from app.config import settings as _settings

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------
# Security headers (audit medium fix)
# ----------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Referrer-Policy", "strict-origin-when-cross-origin"
    )
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    if _settings.environment.lower() == "production":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=63072000; includeSubDomains",
        )
    return response


# ----------------------------------------------------
# Global Exception Logging
# ----------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ----------------------------------------------------
# Health checks
#   /health        — liveness (process is up)
#   /health/ready  — readiness (pings the DB)
# ----------------------------------------------------
@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    from sqlalchemy import text
    from app.database import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning("Readiness probe failed: %s", e)
        return JSONResponse(
            status_code=503,
            content={"status": "db_unavailable", "detail": str(e)},
        )
    return {"status": "ready"}


# ----------------------------------------------------
# Routers
# ----------------------------------------------------
from app.routers import stripe
from app.routers import subscription
from app.routers import auth
from app.routers import project
from app.routers import settings as settings_router
from app.routers import billing
from app.routers import segments
from app.routers import segment_comments
from app.routers import export
from app.routers import glossary
from app.routers import translation_memory
from app.routers import members
from app.routers import certifications
from app.routers import ws

app.include_router(settings_router.router)
app.include_router(stripe.router)
app.include_router(subscription.router)
app.include_router(auth.router)
app.include_router(project.router)
app.include_router(billing.router)
app.include_router(segments.router)
app.include_router(segment_comments.router)
app.include_router(export.router)
app.include_router(glossary.router)
app.include_router(translation_memory.router)
app.include_router(members.router)
app.include_router(certifications.router)
app.include_router(ws.router)

logger.info("All routers registered successfully")


# ----------------------------------------------------
# Watchdog (audit HIGH-7) — runs every 60s in a background asyncio
# task. Disabled when SQS_QUEUE_URL is empty so dev environments don't
# spam logs with credential errors.
# ----------------------------------------------------
import asyncio
import os
import threading
from app.services.watchdog import recover_stalled_jobs

WATCHDOG_INTERVAL_SECONDS = 60


async def _watchdog_loop():
    while True:
        try:
            recover_stalled_jobs()
        except Exception:
            logger.exception("Watchdog cycle errored")
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)


def _run_worker_in_thread():
    """Run the Postgres-backed translation worker in a daemon thread.

    On Railway (single service) we want one process that serves HTTP
    AND processes the translation queue. The worker uses a blocking
    `while True` poll loop with `time.sleep`, so we put it in its own
    thread to keep the asyncio event loop free.

    Disable by setting RUN_WORKER_INLINE=0 if you ever want to split
    web and worker into separate Railway services.
    """
    try:
        from app.workers.sqs_worker import start_worker
        logger.info("🛠️  Starting in-process translation worker thread")
        start_worker()
    except Exception:
        logger.exception("In-process worker crashed")


@app.on_event("startup")
async def _start_watchdog():
    # The queue is now Postgres-backed (translation_jobs table), so
    # the watchdog runs unconditionally — it just sweeps stalled
    # `processing` jobs back to `pending` so a crashed worker doesn't
    # leave projects in limbo.
    asyncio.create_task(_watchdog_loop())
    logger.info(
        "Watchdog scheduled every %ss", WATCHDOG_INTERVAL_SECONDS
    )

    # Spin up the translation worker in a daemon thread so a single
    # Railway service handles both HTTP and queue processing. Set
    # RUN_WORKER_INLINE=0 to opt out (e.g. when running a dedicated
    # worker service).
    if os.getenv("RUN_WORKER_INLINE", "1") != "0":
        t = threading.Thread(
            target=_run_worker_in_thread,
            name="translation-worker",
            daemon=True,
        )
        t.start()
        logger.info("Translation worker thread started")
    else:
        logger.info(
            "RUN_WORKER_INLINE=0 — skipping in-process worker"
        )
