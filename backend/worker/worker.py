import logging
from pathlib import Path

from worker.services.sqs_worker_service import receive_job, delete_job
from worker.services.s3_worker_service import download_file, upload_file
from worker.processors.translation_processor import process_translation, extract_paragraphs
from worker.services.db_service import get_db
from worker.services.segment_service import store_segments

from app.models.project import TranslationProject, ProjectStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WORK_DIR = Path("worker_temp")
WORK_DIR.mkdir(exist_ok=True)


def run_worker():

    logger.info("Worker started")

    while True:

        job = receive_job()

        if not job:
            continue

        body, receipt = job

        project_id = body["project_id"]
        file_key = body["file_key"]

        logger.info(f"Processing project {project_id}")

        db = get_db()

        try:

            # --------------------------------------------------
            # Set project status to PROCESSING
            # --------------------------------------------------
            project = db.query(TranslationProject).filter(
                TranslationProject.id == project_id
            ).first()

            if not project:
                logger.error(f"Project {project_id} not found")
                delete_job(receipt)
                continue

            project.status = ProjectStatus.PROCESSING
            db.commit()

            # --------------------------------------------------
            # Download file from S3
            # --------------------------------------------------
            local_input = WORK_DIR / file_key.split("/")[-1]

            download_file(file_key, local_input)

            # --------------------------------------------------
            # STEP 4: Extract document segments
            # --------------------------------------------------
            paragraphs = extract_paragraphs(local_input)

            if paragraphs:
                store_segments(db, project_id, paragraphs)
                logger.info(f"{len(paragraphs)} segments created for project {project_id}")

            # --------------------------------------------------
            # Process translation
            # --------------------------------------------------
            output_file = process_translation(local_input)

            output_key = f"outputs/{output_file.name}"

            # --------------------------------------------------
            # Upload translated file
            # --------------------------------------------------
            upload_file(output_file, output_key)

            # --------------------------------------------------
            # Mark project as COMPLETED
            # --------------------------------------------------
            project.status = ProjectStatus.COMPLETED
            project.output_file = output_key
            project.progress_percent = 100

            db.commit()

            # --------------------------------------------------
            # Delete SQS job
            # --------------------------------------------------
            delete_job(receipt)

            logger.info(f"Project {project_id} completed")

        except Exception as e:

            logger.exception(f"Worker failed processing project {project_id}")

            project = db.query(TranslationProject).filter(
                TranslationProject.id == project_id
            ).first()

            if project:
                project.status = ProjectStatus.FAILED
                db.commit()

        finally:
            db.close()


if __name__ == "__main__":
    run_worker()