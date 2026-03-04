import logging
import tempfile
import shutil
import time

from pathlib import Path
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.project import TranslationProject, ProjectStatus
from app.database import SessionLocal
from app.services.s3_service import download_file_from_s3, upload_file_to_s3

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


# ============================================================
# TRANSLATION WORKER
# ============================================================

def process_translation_job(project_id: str):
    logger.info(f"Worker starting processing for {project_id}")

    db: Session = SessionLocal()
    temp_dir = None

    try:
        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_id
        ).first()

        if not project:
            logger.warning("Worker project not found")
            return

        logger.info("Worker project found")

        # ----------------------------------------------------
        # Crash Recovery Detection
        # ----------------------------------------------------
        if (
            project.status == ProjectStatus.PROCESSING
            and project.last_heartbeat
            and datetime.utcnow() - project.last_heartbeat > timedelta(seconds=60)
        ):
            logger.warning("Detected stale PROCESSING job. Resetting to PENDING.")
            project.status = ProjectStatus.PENDING
            db.commit()

        # ----------------------------------------------------
        # Completed Guard
        # ----------------------------------------------------
        if project.status == ProjectStatus.COMPLETED:
            logger.info("Worker job already completed")
            return

        # ----------------------------------------------------
        # Retry Limit Guard
        # ----------------------------------------------------
        if project.retry_count >= MAX_ATTEMPTS:
            logger.error("Max retry attempts reached. Marking FAILED.")
            project.status = ProjectStatus.FAILED
            db.commit()
            return

        # ----------------------------------------------------
        # Begin Processing
        # ----------------------------------------------------
        project.retry_count += 1
        project.last_heartbeat = datetime.utcnow()
        project.status = ProjectStatus.PROCESSING
        project.progress_percent = 0
        db.commit()

        logger.info(f"Worker attempt #{project.retry_count}")

        # ----------------------------------------------------
        # Create temp working directory
        # ----------------------------------------------------
        temp_dir = Path(tempfile.mkdtemp())

        input_file = temp_dir / project.file_name

        logger.info("Downloading source file from S3")

        download_file_from_s3(
            project.file_path,
            input_file
        )

        # ----------------------------------------------------
        # Simulated Processing
        # ----------------------------------------------------
        total_steps = 4

        for i in range(total_steps):
            time.sleep(1)

            project.progress_percent = int(((i + 1) / total_steps) * 100)
            project.last_heartbeat = datetime.utcnow()
            db.commit()

            logger.info(f"Worker progress: {project.progress_percent}%")

        # ----------------------------------------------------
        # Generate translated output
        # ----------------------------------------------------
        output_filename = f"translated_{project.file_name}"
        output_file = temp_dir / output_filename

        shutil.copyfile(input_file, output_file)

        logger.info("Uploading translated output to S3")

        output_s3_key = upload_file_to_s3(output_file)

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------
        project.output_file = output_s3_key
        project.status = ProjectStatus.COMPLETED
        project.progress_percent = 100
        project.last_heartbeat = datetime.utcnow()

        db.commit()

        logger.info("Worker completed successfully")

    except Exception:
        logger.exception("Worker processing failed")
        db.rollback()

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_id
        ).first()

        if project:
            if project.retry_count >= MAX_ATTEMPTS:
                project.status = ProjectStatus.FAILED
                logger.error("Worker permanently failed after max retries")
            else:
                project.status = ProjectStatus.PENDING
                logger.warning("Worker returned job to PENDING for retry")

            db.commit()

    finally:

        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

        db.close()


# ============================================================
# WATCHDOG RECOVERY
# ============================================================

def recover_stalled_jobs():
    logger.info("Watchdog checking for stalled jobs")

    db: Session = SessionLocal()

    try:
        timeout_threshold = datetime.utcnow() - timedelta(minutes=2)

        stalled_projects = db.query(TranslationProject).filter(
            TranslationProject.status == ProjectStatus.PROCESSING,
            TranslationProject.last_heartbeat < timeout_threshold
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
        logger.exception("Watchdog recovery failed")

    finally:
        db.close()