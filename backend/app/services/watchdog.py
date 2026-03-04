import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import SessionLocal
from app.models.project import TranslationProject, ProjectStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
STALL_TIMEOUT_MINUTES = 2


def recover_stalled_jobs():
    logger.info("Watchdog checking for stalled jobs")

    db: Session = SessionLocal()

    try:
        timeout_threshold = datetime.utcnow() - timedelta(
            minutes=STALL_TIMEOUT_MINUTES
        )

        stalled_projects = db.query(TranslationProject).filter(
            TranslationProject.status == ProjectStatus.PROCESSING,
            or_(
                TranslationProject.last_heartbeat == None,
                TranslationProject.last_heartbeat < timeout_threshold
            )
        ).all()

        logger.info(f"Watchdog found {len(stalled_projects)} stalled jobs")

        for project in stalled_projects:
            logger.info(f"Watchdog recovering project {project.id}")

            if project.retry_count >= MAX_ATTEMPTS:
                project.status = ProjectStatus.FAILED
                logger.error("Watchdog marked project FAILED")
            else:
                project.status = ProjectStatus.PENDING
                logger.warning("Watchdog returned project to PENDING")

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Watchdog recovery failed")

    finally:
        db.close()