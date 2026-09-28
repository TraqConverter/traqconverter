"""Recovers queue jobs whose worker died, and fails projects that have no live job."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.project import ProjectStatus, TranslationProject
from app.services.ai_actions import expire_stale_rebuilds
from app.services.project_lifecycle import mark_project_failed
from app.workers.sqs_worker import MAX_ATTEMPTS

logger = logging.getLogger(__name__)

# Workers refresh locked_at every 30s, so this only trips when a worker is gone.
STALL_TIMEOUT_MINUTES = 10


def recover_stalled_jobs():
    db: Session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=STALL_TIMEOUT_MINUTES)

        reset = db.execute(
            text(
                """
                UPDATE translation_jobs
                   SET status = 'pending', locked_at = NULL, locked_by = NULL, updated_at = timezone('utc', now()),
                       last_error = COALESCE(last_error, '') || '[watchdog: worker lost]'
                 WHERE id IN (
                       SELECT id FROM translation_jobs
                        WHERE status = 'processing' AND locked_at < :cutoff AND attempts < :max
                        FOR UPDATE SKIP LOCKED)
             RETURNING project_id
                """
            ),
            {"cutoff": cutoff, "max": MAX_ATTEMPTS},
        ).fetchall()

        exhausted = db.execute(
            text(
                """
                UPDATE translation_jobs
                   SET status = 'failed', updated_at = timezone('utc', now()),
                       last_error = COALESCE(last_error, '') || '[watchdog: retries exhausted]'
                 WHERE id IN (
                       SELECT id FROM translation_jobs
                        WHERE attempts >= :max
                          AND ((status = 'processing' AND locked_at < :cutoff) OR status = 'pending')
                        FOR UPDATE SKIP LOCKED)
             RETURNING project_id
                """
            ),
            {"cutoff": cutoff, "max": MAX_ATTEMPTS},
        ).fetchall()
        db.commit()
        if reset:
            logger.warning("Watchdog re-queued %d jobs from lost workers", len(reset))

        # Projects still in flight with no pending/processing job can never finish.
        orphans = (
            db.query(TranslationProject)
            .filter(
                TranslationProject.status.in_([ProjectStatus.PENDING, ProjectStatus.PROCESSING]),
                TranslationProject.created_at < cutoff,
                text(
                    "NOT EXISTS (SELECT 1 FROM translation_jobs j WHERE j.project_id = translation_projects.id "
                    "AND j.status IN ('pending', 'processing'))"
                ),
            )
            .with_for_update(skip_locked=True)
            .all()
        )
        for project in orphans:
            mark_project_failed(db, project, "Translation failed; credits were refunded")
            logger.error("Watchdog failed orphaned project %s", project.id)
        expired = expire_stale_rebuilds(db)
        db.commit()
        if expired:
            logger.warning("Watchdog expired %d interrupted rebuilds", expired)
        if exhausted:
            logger.warning("Watchdog closed %d exhausted jobs", len(exhausted))
    except Exception:
        db.rollback()
        logger.exception("Watchdog recovery failed")
    finally:
        db.close()
