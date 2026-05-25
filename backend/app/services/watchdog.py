"""Watchdog — recover stalled translation jobs.

Runs every minute from the FastAPI startup hook. Scans for:

  1. translation_jobs rows in `processing` that haven't been updated
     for longer than STALL_TIMEOUT_MINUTES (worker crashed mid-job).
     Flipped back to `pending` so another worker picks them up.

  2. translation_projects in PROCESSING with no heartbeat for the
     same window. Status reset to PENDING and a fresh row inserted
     in translation_jobs.

No SQS dependency. The boto3 import that used to live here is gone.
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import or_, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.project import TranslationProject, ProjectStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
STALL_TIMEOUT_MINUTES = 2

# Set once we've observed a missing translation_jobs table so we stop
# spamming the logs while migrations haven't been applied yet.
_jobs_table_warning_logged = False


def recover_stalled_jobs():
    logger.info("Watchdog checking for stalled jobs")

    db: Session = SessionLocal()
    try:
        timeout_threshold = datetime.utcnow() - timedelta(
            minutes=STALL_TIMEOUT_MINUTES
        )

        # 1. Reset stalled translation_jobs rows. SELECT FOR UPDATE
        #    SKIP LOCKED prevents racing with a running worker.
        reset = db.execute(
            text(
                """
                UPDATE translation_jobs
                   SET status     = 'pending',
                       locked_at  = NULL,
                       locked_by  = NULL,
                       updated_at = NOW(),
                       last_error = COALESCE(last_error, '') ||
                                    '[watchdog: reset stalled job]'
                 WHERE id IN (
                       SELECT id FROM translation_jobs
                        WHERE status = 'processing'
                          AND locked_at < :cutoff
                          AND attempts < :max_attempts
                        FOR UPDATE SKIP LOCKED
                 )
                 RETURNING id
                """
            ),
            {"cutoff": timeout_threshold, "max_attempts": MAX_ATTEMPTS},
        ).fetchall()
        db.commit()
        if reset:
            logger.warning(
                "Watchdog reset %d stalled translation_jobs rows", len(reset)
            )

        # 2. Sweep projects whose heartbeat went silent without a
        #    corresponding pending/processing job (worker crashed and
        #    didn't even get to flip the job to processing). Re-enqueue.
        stalled_projects = (
            db.query(TranslationProject)
            .filter(
                TranslationProject.status == ProjectStatus.PROCESSING,
                or_(
                    TranslationProject.last_heartbeat == None,
                    TranslationProject.last_heartbeat < timeout_threshold,
                ),
            )
            .all()
        )
        logger.info(
            "Watchdog found %d stalled projects", len(stalled_projects)
        )

        for project in stalled_projects:
            if project.retry_count >= MAX_ATTEMPTS:
                project.status = ProjectStatus.FAILED
                logger.error(
                    "Project %s marked FAILED (max retries)", project.id
                )
                continue

            project.status = ProjectStatus.PENDING
            project.last_heartbeat = None
            project.retry_count = (project.retry_count or 0) + 1
            db.commit()

            # Drop a pending row so a worker re-runs it. file_path on
            # the project holds the S3 / Supabase object key.
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
                    {
                        "project_id": str(project.id),
                        "s3_key": project.file_path or "",
                    },
                )
                db.commit()
                logger.info("🔁 Re-enqueued project %s", project.id)
            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to re-enqueue project %s", project.id
                )

        logger.info("Watchdog recovery cycle complete")
    except Exception:
        db.rollback()
        logger.exception("Watchdog recovery failed")
    finally:
        db.close()
