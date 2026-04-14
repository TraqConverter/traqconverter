import logging
import tempfile
import shutil
import time
import re
import os
import asyncio

import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

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

from app.routers.ws import broadcast_progress

from docx import Document
import fitz  # 🔥 USE PyMuPDF INSTEAD (MORE RELIABLE)
from PIL import Image

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BATCH_SIZE = 20


# ============================================================
# 🔥 FIXED TEXT EXTRACTION
# ============================================================
def extract_file_text(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()

    # =========================
    # PDF (FIXED)
    # =========================
    if ext == ".pdf":
        text = ""

        try:
            doc = fitz.open(file_path)

            for page in doc:
                text += page.get_text()

            doc.close()

        except Exception as e:
            raise Exception(f"PDF extraction failed: {e}")

        # 🔥 FALLBACK TO OCR IF EMPTY
        if not text.strip():
            try:
                logger.warning("PDF text empty → using OCR fallback")

                doc = fitz.open(file_path)
                for page in doc:
                    pix = page.get_pixmap()
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    text += pytesseract.image_to_string(img)

                doc.close()
            except Exception as e:
                raise Exception(f"OCR fallback failed: {e}")

        if not text.strip():
            raise Exception("PDF has no extractable text")

        return text

    # =========================
    # DOCX
    # =========================
    elif ext == ".docx":
        try:
            doc = Document(file_path)
            text = "\n".join([
                p.text.strip()
                for p in doc.paragraphs
                if p.text and p.text.strip()
            ])
        except Exception as e:
            raise Exception(f"DOCX extraction failed: {e}")

        if not text.strip():
            raise Exception("DOCX has no extractable text")

        return text

    # =========================
    # TXT
    # =========================
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    # =========================
    # IMAGE (OCR)
    # =========================
    elif ext in [".jpg", ".jpeg", ".png"]:
        try:
            image = Image.open(file_path)
            return pytesseract.image_to_string(image)
        except Exception as e:
            raise Exception(f"Image OCR failed: {e}")

    # =========================
    # UNSUPPORTED
    # =========================
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
            logger.warning("Worker project not found")
            return

        project.retry_count += 1
        project.status = ProjectStatus.PROCESSING
        project.progress_percent = 0
        project.translated_segments = 0
        project.last_heartbeat = datetime.utcnow()
        db.commit()

        temp_dir = Path(tempfile.mkdtemp())
        input_file = temp_dir / project.file_name

        download_file_from_s3(project.file_path, input_file)

        text = extract_file_text(str(input_file))

        if not text or not text.strip():
            raise Exception("Failed to extract text")

        # =========================
        # SEGMENTATION
        # =========================
        raw_sentences = re.split(r'[.\n]+', text)

        sentences = [
            s.strip()
            for s in raw_sentences
            if s.strip() and len(s.strip()) > 2 and not s.strip().isdigit()
        ]

        db.query(TranslationSegment).filter(
            TranslationSegment.project_id == project_uuid
        ).delete()
        db.commit()

        segments = []

        for index, s in enumerate(sentences):
            seg = TranslationSegment(
                project_id=project_uuid,
                segment_index=index,
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

        # =========================
        # TRANSLATION LOOP
        # =========================
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
                continue

            for j, (src, translated) in enumerate(zip(batch, translations)):
                seg = segments[i + j]
                seg.translated_text = translated

                # TM SAVE
                try:
                    store_tm_entry(
                        db=db,
                        team_id=project.team_id,
                        source_language=source_lang,
                        target_language=target_lang,
                        source_text=src,
                        translated_text=translated
                    )
                except Exception:
                    pass

                project.translated_segments += 1

                if project.translated_segments % 5 == 0:
                    progress = int(
                        (project.translated_segments / project.total_segments) * 100
                    )

                    project.progress_percent = progress
                    project.last_heartbeat = datetime.utcnow()
                    db.commit()

                    try:
                        asyncio.run(
                            broadcast_progress(
                                str(project.id),
                                {
                                    "project_id": str(project.id),
                                    "progress": progress,
                                    "status": project.status.value
                                }
                            )
                        )
                    except Exception as e:
                        logger.warning(f"WS broadcast failed: {e}")

            db.commit()

        project.progress_percent = 100
        project.status = ProjectStatus.COMPLETED
        project.last_heartbeat = datetime.utcnow()
        db.commit()

        try:
            asyncio.run(
                broadcast_progress(
                    str(project.id),
                    {
                        "project_id": str(project.id),
                        "progress": 100,
                        "status": ProjectStatus.COMPLETED.value
                    }
                )
            )
        except Exception as e:
            logger.warning(f"Final WS broadcast failed: {e}")

        output_file = temp_dir / f"translated_{project.file_name}"
        shutil.copyfile(input_file, output_file)

        output_s3_key = upload_file_to_s3(output_file)
        project.output_file = output_s3_key
        db.commit()

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