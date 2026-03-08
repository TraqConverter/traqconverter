import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from worker.services.sqs_worker_service import receive_job, delete_job
from worker.services.s3_worker_service import download_file, upload_file
from worker.processors.translation_processor import process_translation, extract_paragraphs
from worker.services.db_service import get_db
from worker.services.segment_service import store_segments
from worker.services.pdf_reconstruction_service import build_searchable_pdf
from worker.services.ocr_service import extract_text_with_textract
from worker.services.docx_service import extract_text_from_docx

from app.services.pdf_detection_service import pdf_has_text
from app.models.project import TranslationProject, ProjectStatus
from app.models.translation_segment import TranslationSegment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WORK_DIR = Path("worker_temp")
WORK_DIR.mkdir(exist_ok=True)


def process_job(body, receipt):

    project_id = body["project_id"]
    file_key = body["file_key"]

    logger.info(f"Processing project {project_id}")

    db = get_db()

    try:

        # --------------------------------------------------
        # Load project
        # --------------------------------------------------

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_id
        ).first()

        if not project:
            logger.error(f"Project {project_id} not found")
            delete_job(receipt)
            return

        project.status = ProjectStatus.PROCESSING
        db.commit()

        # --------------------------------------------------
        # Download file
        # --------------------------------------------------

        local_input = WORK_DIR / file_key.split("/")[-1]

        download_file(file_key, local_input)

        # --------------------------------------------------
        # Detect file type
        # --------------------------------------------------

        file_ext = local_input.suffix.lower()

        # -------------------------
        # PDF
        # -------------------------

        if file_ext == ".pdf":

            if pdf_has_text(str(local_input)):

                logger.info("PDF contains selectable text")

                paragraphs = extract_paragraphs(local_input)

            else:

                logger.info("Scanned PDF detected — routing through Textract")

                paragraphs = extract_text_with_textract(local_input)

        # -------------------------
        # DOCX
        # -------------------------

        elif file_ext == ".docx":

            logger.info("DOCX file detected")

            paragraphs = extract_text_from_docx(local_input)

        # -------------------------
        # Images
        # -------------------------

        elif file_ext in [".jpg", ".jpeg", ".png"]:

            logger.info("Image detected — using Textract OCR")

            paragraphs = extract_text_with_textract(local_input)

        else:

            raise Exception(f"Unsupported file type: {file_ext}")

        # --------------------------------------------------
        # Store segments
        # --------------------------------------------------

        if paragraphs:

            store_segments(
                db,
                project.id,
                project.team_id,
                project.source_language,
                project.target_language,
                paragraphs
            )

            logger.info(f"{len(paragraphs)} segments created for project {project_id}")

        # --------------------------------------------------
        # Process translation
        # --------------------------------------------------

        process_translation(local_input)

        # --------------------------------------------------
        # Collect translated lines
        # --------------------------------------------------

        segments = db.query(TranslationSegment).filter(
            TranslationSegment.project_id == project.id
        ).order_by(
            TranslationSegment.segment_index
        ).all()

        translated_lines = [
            s.translated_text for s in segments if s.translated_text
        ]

        # --------------------------------------------------
        # Build searchable PDF
        # --------------------------------------------------

        output_file = build_searchable_pdf(
            local_input,
            translated_lines
        )

        output_key = f"outputs/{output_file.name}"

        # --------------------------------------------------
        # Upload translated file
        # --------------------------------------------------

        upload_file(output_file, output_key)

        # --------------------------------------------------
        # Mark project completed
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

    except Exception:

        logger.exception(f"Worker failed processing project {project_id}")

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_id
        ).first()

        if project:
            project.status = ProjectStatus.FAILED
            db.commit()

    finally:

        db.close()


def run_worker():

    logger.info("Worker started")

    executor = ThreadPoolExecutor(max_workers=5)

    while True:

        job = receive_job()

        if not job:
            continue

        body, receipt = job

        executor.submit(process_job, body, receipt)


if __name__ == "__main__":
    run_worker()