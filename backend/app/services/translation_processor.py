import logging
import tempfile
import shutil
import time
import re
import os

import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

from pathlib import Path
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.project import TranslationProject, ProjectStatus
from app.models.translation_segment import TranslationSegment
from app.database import SessionLocal
from app.services.s3_service import download_file_from_s3, upload_file_to_s3
from app.services.ai_translation_service import translate_batch
from app.services.glossary_service import get_glossary
from app.services.translation_memory_service import store_tm_entry  # 🔥 NEW

from docx import Document
from pdfminer.high_level import extract_text
from PIL import Image

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BATCH_SIZE = 20


# ============================================================
# FILE TEXT EXTRACTION
# ============================================================
def extract_file_text(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return extract_text(file_path)

    elif ext == ".docx":
        doc = Document(file_path)
        return "\n".join([
            p.text.strip()
            for p in doc.paragraphs
            if p.text and p.text.strip()
        ])

    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    elif ext in [".jpg", ".jpeg", ".png"]:
        image = Image.open(file_path)
        return pytesseract.image_to_string(image)

    else:
        raise Exception(f"Unsupported file type: {ext}")


# ============================================================
# TRANSLATION WORKER
# ============================================================
def process_translation_job(project_id: str):
    logger.info(f"Worker starting processing for {project_id}")

    db: Session = SessionLocal()
    temp_dir = None

    try:
        project_uuid = UUID(project_id)

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_uuid
        ).first()

        if not project:
            logger.warning("Worker project not found")
            return

        logger.info("Worker project found")

        # ----------------------------------------------------
        # Crash Recovery
        # ----------------------------------------------------
        if (
            project.status == ProjectStatus.PROCESSING
            and project.last_heartbeat
            and datetime.utcnow() - project.last_heartbeat > timedelta(seconds=60)
        ):
            logger.warning("Resetting stalled job to PENDING")
            project.status = ProjectStatus.PENDING
            db.commit()

        if project.status == ProjectStatus.COMPLETED:
            logger.info("Job already completed")
            return

        if project.retry_count >= MAX_ATTEMPTS:
            project.status = ProjectStatus.FAILED
            db.commit()
            return

        # ----------------------------------------------------
        # Start processing
        # ----------------------------------------------------
        project.retry_count += 1
        project.status = ProjectStatus.PROCESSING
        project.progress_percent = 0
        project.last_heartbeat = datetime.utcnow()
        db.commit()

        temp_dir = Path(tempfile.mkdtemp())
        input_file = temp_dir / project.file_name

        logger.info("Downloading file from S3")
        download_file_from_s3(project.file_path, input_file)

        # ----------------------------------------------------
        # TEXT EXTRACTION
        # ----------------------------------------------------
        logger.info("Extracting text")

        text = extract_file_text(str(input_file))

        if not text or not text.strip():
            raise Exception("Failed to extract text")

        # ----------------------------------------------------
        # CLEAN SEGMENTATION
        # ----------------------------------------------------
        logger.info("Creating clean segments")

        raw_sentences = re.split(r'[.\n]+', text)

        sentences = []

        for s in raw_sentences:
            s = s.strip()

            if not s:
                continue
            if len(s) < 3:
                continue
            if s.isdigit():
                continue
            if s.lower() in ["co", "za"]:
                continue

            sentences.append(s)

        # ----------------------------------------------------
        # CLEAR OLD SEGMENTS
        # ----------------------------------------------------
        db.query(TranslationSegment).filter(
            TranslationSegment.project_id == project_uuid
        ).delete()

        db.commit()

        segments = []

        for index, s in enumerate(sentences):
            segment = TranslationSegment(
                project_id=project_uuid,
                segment_index=index,
                source_text=s,
                translated_text=""
            )
            db.add(segment)
            segments.append(segment)

        db.commit()

        logger.info(f"✅ {len(segments)} clean segments created")

        # ----------------------------------------------------
        # TRANSLATION
        # ----------------------------------------------------
        logger.info("Starting translation")

        texts = [s.source_text for s in segments]

        source_lang = project.source_language or "English"
        target_lang = project.target_language or "Spanish"

        # ----------------------------------------------------
        # LOAD GLOSSARY
        # ----------------------------------------------------
        try:
            glossary_entries = get_glossary(
                db,
                project.team_id,  # ✅ FIXED
                source_lang,
                target_lang
            )
            logger.info(f"Loaded {len(glossary_entries)} glossary terms")
        except Exception as e:
            logger.warning(f"Glossary load failed: {e}")

        # ----------------------------------------------------
        # BATCH TRANSLATION + AUTO TM 🔥
        # ----------------------------------------------------
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]

            translations = translate_batch(
                batch,
                source_lang,
                target_lang,
                db=db,
                project=project
            )

            if len(translations) != len(batch):
                logger.warning("Translation mismatch, skipping batch")
                continue

            for j, (src, translated) in enumerate(zip(batch, translations)):
                segments[i + j].translated_text = translated

                # 🔥 AUTO TM LEARNING
                try:
                    if src.strip() and translated.strip():
                        store_tm_entry(
                            db=db,
                            team_id=project.team_id,
                            source_language=source_lang,
                            target_language=target_lang,
                            source_text=src,
                            translated_text=translated
                        )
                except Exception as e:
                    logger.error(f"TM STORE ERROR: {e}")

            db.commit()

            logger.info(f"Translated batch {i} → {i + len(batch)} (TM saved)")

        logger.info("✅ Translation complete")

        # ----------------------------------------------------
        # PROGRESS
        # ----------------------------------------------------
        for i in range(4):
            time.sleep(1)
            project.progress_percent = int(((i + 1) / 4) * 100)
            project.last_heartbeat = datetime.utcnow()
            db.commit()

        # ----------------------------------------------------
        # OUTPUT
        # ----------------------------------------------------
        output_file = temp_dir / f"translated_{project.file_name}"
        shutil.copyfile(input_file, output_file)

        logger.info("Uploading output")
        output_s3_key = upload_file_to_s3(output_file)

        project.output_file = output_s3_key
        project.status = ProjectStatus.COMPLETED
        project.progress_percent = 100
        project.last_heartbeat = datetime.utcnow()

        db.commit()

        logger.info("✅ Worker completed")

    except Exception:
        logger.exception("Worker failed")
        db.rollback()

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_id
        ).first()

        if project:
            project.status = (
                ProjectStatus.FAILED
                if project.retry_count >= MAX_ATTEMPTS
                else ProjectStatus.PENDING
            )
            db.commit()

    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

        db.close()