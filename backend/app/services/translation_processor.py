import logging
import tempfile
import shutil
import re
import os
import asyncio

import pytesseract

# ============================================================
# CROSS-PLATFORM TESSERACT CONFIG
# ============================================================
TESSERACT_PATH = os.getenv("TESSERACT_CMD")

if TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    logging.getLogger(__name__).info(f"Using Tesseract from ENV: {TESSERACT_PATH}")
else:
    # fallback to PATH
    logging.getLogger(__name__).info("Using Tesseract from system PATH")

from pathlib import Path
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.project import TranslationProject, ProjectStatus
from app.models.translation_segment import TranslationSegment
from app.database import SessionLocal
from app.services.s3_service import download_file_from_s3, upload_file_to_s3
from app.services.ai_translation_service import translate_batch
from app.services.translation_memory_service import store_tm_entry
from app.services.certification_service import CertificationService
from app.routers.ws import broadcast_progress

from docx import Document
import fitz
from PIL import Image

logger = logging.getLogger(__name__)

BATCH_SIZE = 20


# ============================================================
# TEXT EXTRACTION
# ============================================================
def extract_file_text(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        text = ""
        doc = fitz.open(file_path)

        for page in doc:
            text += page.get_text()

        doc.close()

        if not text.strip():
            logger.warning("PDF empty → OCR fallback")

            try:
                doc = fitz.open(file_path)

                for page in doc:
                    pix = page.get_pixmap()
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    text += pytesseract.image_to_string(img)

                doc.close()

            except Exception as e:
                logger.error("OCR failed — check Tesseract installation")
                raise Exception(f"OCR failed: {e}")

        return text

    elif ext == ".docx":
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

    elif ext == ".txt":
        return open(file_path, "r", encoding="utf-8").read()

    elif ext in [".jpg", ".jpeg", ".png"]:
        try:
            image = Image.open(file_path)
            return pytesseract.image_to_string(image)
        except Exception as e:
            logger.error("Image OCR failed")
            raise Exception(f"OCR failed: {e}")

    else:
        raise Exception(f"Unsupported file type: {ext}")


# ============================================================
# MAIN WORKER
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
            return

        project.status = ProjectStatus.PROCESSING
        project.progress_percent = 0
        project.translated_segments = 0
        project.last_heartbeat = datetime.utcnow()
        db.commit()

        temp_dir = Path(tempfile.mkdtemp())
        input_file = temp_dir / project.file_name

        download_file_from_s3(project.file_path, input_file)

        text = extract_file_text(str(input_file))
        text = re.sub(r"\s+", " ", text)

        sentences = [
            s.strip()
            for s in re.split(r"[.\n]+", text)
            if s.strip() and len(s.strip()) > 2
        ]

        db.query(TranslationSegment).filter(
            TranslationSegment.project_id == project_uuid
        ).delete()
        db.commit()

        segments = []

        for i, s in enumerate(sentences):
            seg = TranslationSegment(
                project_id=project_uuid,
                segment_index=i,
                source_text=s,
                translated_text=""
            )
            db.add(seg)
            segments.append(seg)

        db.commit()

        project.total_segments = len(segments)
        db.commit()

        logger.info(f"{len(segments)} segments created")

        texts = [s.source_text for s in segments]

        source_lang = project.source_language or "English"
        target_lang = project.target_language or "Spanish"

        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]

            try:
                translations = translate_batch(
                    batch,
                    source_lang,
                    target_lang,
                    db=db,
                    project=project
                )
            except Exception as e:
                logger.error(f"Batch failed: {e}")
                continue

            if not translations or len(translations) != len(batch):
                logger.warning("Mismatch — skipping batch")
                continue

            for j, translated in enumerate(translations):
                seg = segments[i + j]

                clean = (translated or "").strip()

                if not clean:
                    continue

                seg.translated_text = clean

                try:
                    store_tm_entry(
                        db=db,
                        team_id=project.team_id,
                        source_language=source_lang,
                        target_language=target_lang,
                        source_text=seg.source_text,
                        translated_text=clean
                    )
                except Exception:
                    pass

                project.translated_segments += 1

            db.commit()

            progress = int(
                (project.translated_segments / project.total_segments) * 100
            )

            project.progress_percent = progress
            project.last_heartbeat = datetime.utcnow()
            db.commit()

        project.progress_percent = 100
        project.status = ProjectStatus.COMPLETED
        db.commit()

        output_file = temp_dir / f"translated_{project.file_name}"
        shutil.copyfile(input_file, output_file)

        output_s3_key = upload_file_to_s3(output_file)
        project.output_file = output_s3_key
        db.commit()

        try:
            cert_file = temp_dir / f"{project.id}_certification.pdf"

            CertificationService.generate_certification_pdf(
                output_path=cert_file,
                user_name="Certified Translator",
                source_language=source_lang,
                target_language=target_lang,
            )

            cert_s3_key = upload_file_to_s3(cert_file)
            project.certification_file = cert_s3_key
            db.commit()

        except Exception as e:
            logger.error(f"Certification failed: {e}")

        logger.info("Worker completed")

    except Exception:
        logger.exception("Worker failed")
        db.rollback()

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_id
        ).first()

        if project:
            project.status = ProjectStatus.FAILED
            db.commit()

    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

        db.close()