"""Translation worker.

Despite the legacy `sqs_worker.py` filename (kept so Procfile / Docker
ENTRYPOINTs don't break), this worker polls the Postgres-backed
`translation_jobs` table — no SQS dependency anymore.

How it works
------------
Workers compete for pending rows using
`SELECT … FOR UPDATE SKIP LOCKED` which lets many workers run in
parallel without ever picking the same job twice. The claimed row's
status flips from `pending → processing`. On success it becomes
`completed`; on failure it becomes `failed` with the traceback in
`last_error` and retried up to MAX_ATTEMPTS times.

Run with:    python -m app.workers.sqs_worker
Or via the Procfile: `worker: python -m app.workers.sqs_worker`
"""
import json
import logging
import os
import socket
import time
import traceback
import uuid

from sqlalchemy import text

from app.database import SessionLocal
from app.services.translation_processor import process_translation_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# How long to wait between polls when the queue is empty. Postgres can
# handle aggressive polling but 2s gives us a nice cost/responsiveness
# balance.
POLL_INTERVAL_SECONDS = 2
MAX_ATTEMPTS = 3
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def _claim_next_job():
    """Atomically claim the oldest pending job for this worker.

    Returns a dict {id, project_id, s3_key} or None when the queue is
    empty. Uses FOR UPDATE SKIP LOCKED so multiple workers can run
    safely in parallel.
    """
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                UPDATE translation_jobs
                   SET status     = 'processing',
                       locked_at  = NOW(),
                       locked_by  = :worker_id,
                       attempts   = attempts + 1,
                       updated_at = NOW()
                 WHERE id = (
                       SELECT id
                         FROM translation_jobs
                        WHERE status = 'pending'
                          AND attempts < :max_attempts
                        ORDER BY created_at
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                 )
             RETURNING id, project_id, s3_key
                """
            ),
            {"worker_id": WORKER_ID, "max_attempts": MAX_ATTEMPTS},
        ).fetchone()
        db.commit()
        if not row:
            return None
        return {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "s3_key": row.s3_key,
        }
    except Exception:
        db.rollback()
        logger.exception("claim_next_job failed")
        return None
    finally:
        db.close()


def _mark_job(job_id: str, status: str, last_error: str | None = None):
    """Flip a job to `completed` or `failed`."""
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                UPDATE translation_jobs
                   SET status     = :status,
                       last_error = :last_error,
                       updated_at = NOW()
                 WHERE id = :job_id
                """
            ),
            {
                "status": status,
                "last_error": (last_error or "")[:8000] or None,
                "job_id": job_id,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("mark_job failed")
    finally:
        db.close()


def start_worker():
    logger.info("🚀 Translation worker started (id=%s)", WORKER_ID)
    logger.info("Queue backend: Postgres translation_jobs")

    while True:
        try:
            job = _claim_next_job()
        except Exception:
            logger.exception("Unexpected error in claim loop")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if not job:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        job_id = job["id"]
        project_id = job["project_id"]
        logger.info("📥 Processing job=%s project=%s", job_id, project_id)

        try:
            process_translation_job(project_id)
            _mark_job(job_id, "completed")
            logger.info("✅ Completed job=%s project=%s", job_id, project_id)
        except Exception as e:
            tb = traceback.format_exc()
            logger.exception("❌ Job failed: %s", e)
            # If we haven't exhausted retries, leave it pending so it
            # gets picked up again on the next poll.
            db = SessionLocal()
            try:
                row = db.execute(
                    text(
                        "SELECT attempts FROM translation_jobs WHERE id = :id"
                    ),
                    {"id": job_id},
                ).fetchone()
                attempts = int(row.attempts) if row else MAX_ATTEMPTS
            except Exception:
                attempts = MAX_ATTEMPTS
            finally:
                db.close()

            if attempts < MAX_ATTEMPTS:
                # Re-enqueue: drop the lock + back to pending.
                db = SessionLocal()
                try:
                    db.execute(
                        text(
                            """
                            UPDATE translation_jobs
                               SET status     = 'pending',
                                   locked_at  = NULL,
                                   locked_by  = NULL,
                                   last_error = :err,
                                   updated_at = NOW()
                             WHERE id = :id
                            """
                        ),
                        {"err": (tb or "")[:8000], "id": job_id},
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()
                logger.warning(
                    "⚠️ Job re-queued (attempt %d/%d)",
                    attempts, MAX_ATTEMPTS,
                )
            else:
                _mark_job(job_id, "failed", last_error=tb)
                logger.error("☠️ Job exhausted retries → failed")


if __name__ == "__main__":
    start_worker()
