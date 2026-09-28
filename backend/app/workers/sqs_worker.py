"""Postgres-backed translation worker (filename kept for Procfile/Docker compatibility).

Run with: python -m app.workers.sqs_worker
"""
import logging
import os
import socket
import threading
import time
import traceback
import uuid
from contextlib import contextmanager

from sqlalchemy import text

from app.database import SessionLocal
from app.models.project import ProjectStatus, TranslationProject
from app.services.project_lifecycle import fail_project_by_id
from app.services.translation_processor import process_translation_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2
HEARTBEAT_SECONDS = 30
# Each attempt can run a full Opus rebuild, so retries are expensive.
MAX_ATTEMPTS = int(os.getenv("JOB_MAX_ATTEMPTS", "2"))
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def _claim_next_job():
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                UPDATE translation_jobs
                   SET status     = 'processing',
                       locked_at  = timezone('utc', now()),
                       locked_by  = :worker_id,
                       attempts   = attempts + 1,
                       updated_at = timezone('utc', now())
                 WHERE id = (
                       SELECT id
                         FROM translation_jobs
                        WHERE status = 'pending'
                          AND attempts < :max_attempts
                        ORDER BY created_at
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                 )
             RETURNING id, project_id, s3_key, attempts
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
            "attempts": int(row.attempts),
        }
    except Exception:
        db.rollback()
        logger.exception("claim_next_job failed")
        return None
    finally:
        db.close()


def _execute(sql: str, params: dict) -> None:
    db = SessionLocal()
    try:
        db.execute(text(sql), params)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("worker update failed")
    finally:
        db.close()


def _beat(job_id: str, project_id: str) -> None:
    _execute(
        "UPDATE translation_jobs SET locked_at = timezone('utc', now()), updated_at = timezone('utc', now()) "
        "WHERE id = :job_id AND locked_by = :worker_id",
        {"job_id": job_id, "worker_id": WORKER_ID},
    )
    _execute(
        "UPDATE translation_projects SET last_heartbeat = timezone('utc', now()) WHERE id = :pid",
        {"pid": project_id},
    )


@contextmanager
def _heartbeat(job_id: str, project_id: str):
    stop = threading.Event()

    def _loop():
        while not stop.wait(HEARTBEAT_SECONDS):
            _beat(job_id, project_id)

    t = threading.Thread(target=_loop, name=f"heartbeat-{job_id[:8]}", daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=5)


def _requeue(job_id: str, project_id: str, error: str) -> None:
    _execute(
        """
        UPDATE translation_jobs
           SET status = 'pending', locked_at = NULL, locked_by = NULL,
               last_error = :err, updated_at = timezone('utc', now())
         WHERE id = :id
        """,
        {"err": error[:8000], "id": job_id},
    )
    db = SessionLocal()
    try:
        project = db.query(TranslationProject).filter(TranslationProject.id == project_id).first()
        if project and project.status != ProjectStatus.COMPLETED:
            project.status = ProjectStatus.PENDING
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("couldn't reset project %s to PENDING", project_id)
    finally:
        db.close()


def _mark_job(job_id: str, status: str, last_error: str | None = None) -> None:
    _execute(
        "UPDATE translation_jobs SET status = :status, last_error = :err, updated_at = timezone('utc', now()) WHERE id = :id",
        {"status": status, "err": (last_error or "")[:8000] or None, "id": job_id},
    )


def run_job(job: dict) -> None:
    job_id, project_id = job["id"], job["project_id"]
    logger.info("Processing job=%s project=%s attempt=%d", job_id, project_id, job["attempts"])
    try:
        with _heartbeat(job_id, project_id):
            process_translation_job(project_id)
        _mark_job(job_id, "completed")
        logger.info("Completed job=%s project=%s", job_id, project_id)
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("Job %s failed: %s", job_id, e)
        if job["attempts"] < MAX_ATTEMPTS:
            _requeue(job_id, project_id, tb)
            logger.warning("Job %s re-queued (attempt %d/%d)", job_id, job["attempts"], MAX_ATTEMPTS)
        else:
            _mark_job(job_id, "failed", last_error=tb)
            fail_project_by_id(project_id, "Translation failed after retries; credits were refunded")
            logger.error("Job %s exhausted retries", job_id)


def start_worker():
    logger.info("Translation worker started (id=%s)", WORKER_ID)
    while True:
        job = _claim_next_job()
        if not job:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        run_job(job)


if __name__ == "__main__":
    start_worker()
