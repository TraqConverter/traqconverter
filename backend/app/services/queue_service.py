"""Enqueue a translation job.

Uses a Postgres-backed queue (translation_jobs table) by default.
When `SQS_QUEUE_URL` is set we additionally publish the job to SQS
for backwards compatibility — but the Postgres queue is authoritative
and the worker only reads from Postgres now.
"""
import logging
from sqlalchemy import text

from app.database import SessionLocal

logger = logging.getLogger(__name__)


def enqueue_translation_job(project_id: str, file_key: str):
    """Insert a row into translation_jobs so a worker picks it up.

    Idempotency: callers shouldn't enqueue the same project twice in
    the same minute. If they do, the worker's SELECT FOR UPDATE
    SKIP LOCKED ensures the second row gets a fresh claim — it just
    re-runs the project, which is safe because the segment writes
    are upsert-friendly.
    """
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO translation_jobs
                    (project_id, s3_key, status)
                VALUES
                    (:project_id, :s3_key, 'pending')
                """
            ),
            {"project_id": project_id, "s3_key": file_key},
        )
        db.commit()
        logger.info(
            "Job queued: project=%s s3_key=%s", project_id, file_key
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to enqueue translation job")
        raise
    finally:
        db.close()
