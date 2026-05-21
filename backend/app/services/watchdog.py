import logging
import json
import boto3
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import SessionLocal
from app.models.project import TranslationProject, ProjectStatus
from app.config import settings

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
STALL_TIMEOUT_MINUTES = 2

# SQS CLIENT
sqs = boto3.client(
    "sqs",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_REGION
)

QUEUE_URL = settings.SQS_QUEUE_URL


# ============================================================
# RE-ENQUEUE FUNCTION
# ============================================================
def requeue_project(project_id: str):
    try:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "project_id": str(project_id)
            })
        )
        logger.info(f"🔁 Re-enqueued project {project_id}")
    except Exception as e:
        logger.error(f"Failed to requeue project {project_id}: {e}")


# ============================================================
# WATCHDOG
# ============================================================
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
            logger.warning(f"Recovering project {project.id}")

            if project.retry_count >= MAX_ATTEMPTS:
                project.status = ProjectStatus.FAILED
                logger.error(f"Project {project.id} marked FAILED (max retries)")
                continue

            # RESET STATE
            project.status = ProjectStatus.PENDING
            project.last_heartbeat = None

            db.commit()  # commit BEFORE enqueue to avoid race

            # RE-ENQUEUE JOB
            requeue_project(project.id)

        logger.info("Watchdog recovery cycle complete")

    except Exception:
        db.rollback()
        logger.exception("Watchdog recovery failed")

    finally:
        db.close()