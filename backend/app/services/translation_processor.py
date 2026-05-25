import logging
import tempfile
import shutil
import re
import os
import asyncio

import pytesseract

# ============================================================
# CROSS-PLATFORM TESSERACT CONFIG (FIXED)
# ============================================================
TESSERACT_PATH = os.getenv("TESSERACT_CMD")

if TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    logging.getLogger(__name__).info(
        f"Using Tesseract from ENV: {TESSERACT_PATH}"
    )
else:
    import shutil as system_shutil

    detected = system_shutil.which("tesseract")

    # Windows fallback
    if not detected and os.name == "nt":
        default_windows_path = (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        )

        if os.path.exists(default_windows_path):
            detected = default_windows_path

    if detected:
        pytesseract.pytesseract.tesseract_cmd = detected
        logging.getLogger(__name__).info(
            f"Using detected Tesseract: {detected}"
        )
    else:
        logging.getLogger(__name__).warning(
            "Tesseract not detected. OCR will fail unless configured."
        )

from pathlib import Path
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.project import TranslationProject, ProjectStatus
from app.models.translation_segment import TranslationSegment
from app.models.translation_memory import TranslationMemory
from app.database import SessionLocal
from app.services.s3_service import (
    download_file_from_s3,
    upload_file_to_s3
)
from app.services.ai_translation_service import translate_batch, translate_text
from app.services.translation_memory_service import store_tm_entry
from app.services.certification_service import CertificationService
from app.services.layout_translator import (
    extract_segments,
    rebuild_output,
)
from app.routers.ws import broadcast_progress

from docx import Document
import fitz
from PIL import Image

logger = logging.getLogger(__name__)

BATCH_SIZE = 20


# ============================================================
# SAFE PROGRESS BROADCAST
# ============================================================
def safe_broadcast(project_id: str, progress: int, status: str):
    try:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                broadcast_progress(
                    project_id,
                    {
                        "progress": progress,
                        "status": status,
                    }
                )
            )
        except RuntimeError:
            asyncio.run(
                broadcast_progress(
                    project_id,
                    {
                        "progress": progress,
                        "status": status,
                    }
                )
            )
    except Exception as e:
        logger.warning(f"WebSocket broadcast failed: {e}")


# ============================================================
# TEXT EXTRACTION
# ============================================================
def extract_file_text(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()

    # ========================================================
    # PDF
    # ========================================================
    if ext == ".pdf":
        text = ""
        doc = fitz.open(file_path)

        for page in doc:
            text += page.get_text()

        doc.close()

        # OCR fallback
        if not text.strip():
            logger.warning("PDF empty → OCR fallback")

            try:
                doc = fitz.open(file_path)

                for page in doc:
                    pix = page.get_pixmap()
                    img = Image.frombytes(
                        "RGB",
                        [pix.width, pix.height],
                        pix.samples
                    )

                    text += pytesseract.image_to_string(img)

                doc.close()

            except Exception as e:
                logger.error("PDF OCR failed")
                raise Exception(f"OCR failed: {e}")

        return text

    # ========================================================
    # DOCX
    # ========================================================
    elif ext == ".docx":
        doc = Document(file_path)

        return "\n".join(
            [p.text for p in doc.paragraphs if p.text.strip()]
        )

    # ========================================================
    # TXT
    # ========================================================
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    # ========================================================
    # IMAGE
    # ========================================================
    elif ext in [".jpg", ".jpeg", ".png"]:
        try:
            image = Image.open(file_path)

            # Normalize image for OCR
            image = image.convert("RGB")

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
    project = None

    try:
        project_uuid = UUID(project_id)

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_uuid
        ).first()

        if not project:
            raise Exception("Project not found")

        # ====================================================
        # START PROCESSING
        # ====================================================
        project.status = ProjectStatus.PROCESSING
        project.progress_percent = 0
        project.translated_segments = 0
        project.last_heartbeat = datetime.utcnow()

        db.commit()

        safe_broadcast(project_id, 0, "PROCESSING")

        # ====================================================
        # TEMP FILES
        # ====================================================
        temp_dir = Path(tempfile.mkdtemp())

        input_file = temp_dir / project.file_name

        download_file_from_s3(
            project.file_path,
            input_file
        )

        # ====================================================
        # EXTRACT — block/paragraph aware so we can rebuild later.
        # ====================================================
        source_kind, extracted = extract_segments(str(input_file))

        if not extracted:
            raise Exception("No text extracted from file")

        project.source_kind = source_kind
        db.commit()

        # ====================================================
        # RESET SEGMENTS
        # ====================================================
        db.query(TranslationSegment).filter(
            TranslationSegment.project_id == project_uuid
        ).delete()

        db.commit()

        # ====================================================
        # CREATE SEGMENTS — preserve layout metadata.
        # ====================================================
        segments = []

        for i, item in enumerate(extracted):
            seg = TranslationSegment(
                project_id=project_uuid,
                segment_index=i,
                source_text=item.text,
                translated_text="",
                layout_meta=item.layout,
            )

            db.add(seg)
            segments.append(seg)

        db.commit()

        project.total_segments = len(segments)

        db.commit()

        logger.info(f"{len(segments)} segments created (kind={source_kind})")

        # ====================================================
        # TRANSLATE
        # ====================================================
        source_lang = project.source_language or "English"
        target_lang = project.target_language or "Spanish"

        # ====================================================
        # TRANSLATION MEMORY FAST PATH
        # ----------------------------------------------------
        # Only runs when project.use_tm is True (toggle on the new-
        # project page). When the user opts out we don't bulk-load
        # entries and we don't apply hits — every segment goes to the
        # LLM. We also skip storing fresh TM entries below.
        # ====================================================
        use_tm = bool(getattr(project, "use_tm", True))
        apply_glossary = bool(getattr(project, "apply_glossary", True))
        logger.info(
            "Project options for %s: use_tm=%s apply_glossary=%s add_certification=%s",
            project_id,
            use_tm,
            apply_glossary,
            bool(getattr(project, "add_certification", False)),
        )
        if use_tm:
            try:
                tm_rows = (
                    db.query(
                        TranslationMemory.source_text,
                        TranslationMemory.translated_text,
                    )
                    .filter(
                        TranslationMemory.team_id == project.team_id,
                        TranslationMemory.source_language == source_lang,
                        TranslationMemory.target_language == target_lang,
                    )
                    .all()
                )
                tm_map: dict[str, str] = {
                    row.source_text: row.translated_text
                    for row in tm_rows
                    if row.source_text and row.translated_text
                }
            except Exception as e:
                logger.warning(
                    "TM bulk-load failed; proceeding without it: %s", e
                )
                tm_map = {}
        else:
            logger.info("Project opted out of TM — fast path skipped")
            tm_map = {}

        tm_hit_count = 0
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for idx, seg in enumerate(segments):
            cached = tm_map.get(seg.source_text)
            if cached:
                seg.translated_text = cached
                seg.tm_pct = 100
                project.translated_segments += 1
                tm_hit_count += 1
            else:
                miss_indices.append(idx)
                miss_texts.append(seg.source_text)

        if tm_hit_count:
            # Commit TM hits immediately so progress is durable even if
            # a later LLM batch crashes.
            db.commit()
            progress = int(
                (
                    project.translated_segments
                    / max(project.total_segments, 1)
                )
                * 100
            )
            project.progress_percent = progress
            project.last_heartbeat = datetime.utcnow()
            db.commit()
            logger.info(
                "TM fast path: %d/%d segments served from memory (%d%% of doc)",
                tm_hit_count,
                len(segments),
                int((tm_hit_count / max(len(segments), 1)) * 100),
            )
            safe_broadcast(project_id, progress, "PROCESSING")

        # `texts` is now the list of MISS texts we still need the LLM
        # for. We also keep `miss_indices` so we can route translations
        # back to the correct segment when results come back.
        texts = miss_texts

        def _translate_resilient(batch_texts, depth=0):
            """Translate a batch with automatic fall-back on count
            mismatches. Splits failing batches in half, then in quarters,
            etc., and finally falls back to per-segment translation. A
            single segment that fails is left as empty rather than
            blowing up the whole job — a partial result is much better
            than zero translated content for the user.
            """
            if not batch_texts:
                return []

            if len(batch_texts) == 1:
                try:
                    return [
                        translate_text(
                            batch_texts[0],
                            source_lang,
                            target_lang,
                            db=db,
                            project=project,
                        ) or ""
                    ]
                except Exception as e:
                    logger.warning(
                        "Per-segment translation failed (depth=%d): %s",
                        depth, e,
                    )
                    return [""]

            try:
                result = translate_batch(
                    batch_texts,
                    source_lang,
                    target_lang,
                    db=db,
                    project=project,
                )
                if result and len(result) == len(batch_texts):
                    return result
                logger.warning(
                    "Batch count mismatch (expected %d, got %d, depth=%d) — splitting",
                    len(batch_texts),
                    len(result) if result else 0,
                    depth,
                )
            except Exception as e:
                logger.warning(
                    "Batch translation raised (depth=%d): %s — splitting",
                    depth, e,
                )

            if depth > 6:
                return [""] * len(batch_texts)

            mid = max(1, len(batch_texts) // 2)
            left = _translate_resilient(batch_texts[:mid], depth + 1)
            right = _translate_resilient(batch_texts[mid:], depth + 1)
            return left + right

        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            translations = _translate_resilient(batch)

            # _translate_resilient always returns a list of the right
            # length (empty strings for failed segments).
            if len(translations) != len(batch):
                # Defensive shim — should never trip given the recursive
                # fallback above, but pad/truncate just in case.
                translations = (translations + [""] * len(batch))[: len(batch)]

            # =================================================
            # STORE
            # =================================================
            # ============================================
            # PHASE 1 — write segment translations and COMMIT.
            # Map LLM batch results back to the ORIGINAL segment indices
            # via miss_indices (texts/batch only contains TM-miss texts,
            # so segments[i + j] would point at the wrong segment).
            # ============================================
            tm_candidates: list[tuple[str, str]] = []
            for j, translated in enumerate(translations):
                seg_idx = miss_indices[i + j]
                seg = segments[seg_idx]
                clean = (translated or "").strip()
                if not clean:
                    continue
                seg.translated_text = clean
                seg.tm_pct = 0  # not a TM hit
                project.translated_segments += 1
                tm_candidates.append((seg.source_text, clean))

            db.commit()

            # ============================================
            # PHASE 2 — best-effort Translation Memory.
            # Skipped entirely when project.use_tm is False so the user's
            # opt-out is respected (translations made now won't seed
            # future projects' fast path).
            # ============================================
            if use_tm:
                for src_text, tgt_text in tm_candidates:
                    try:
                        store_tm_entry(
                            db=db,
                            team_id=project.team_id,
                            source_language=source_lang,
                            target_language=target_lang,
                            source_text=src_text,
                            translated_text=tgt_text,
                        )
                    except Exception as tm_err:
                        logger.warning(
                            "TM store skipped (%d-char source): %s",
                            len(src_text or ""),
                            tm_err,
                        )
                        try:
                            db.rollback()
                        except Exception:
                            pass

            # =================================================
            # PROGRESS
            # =================================================
            progress = int(
                (
                    project.translated_segments /
                    max(project.total_segments, 1)
                ) * 100
            )

            project.progress_percent = progress
            project.last_heartbeat = datetime.utcnow()

            db.commit()

            safe_broadcast(
                project_id,
                progress,
                "PROCESSING"
            )

        # ====================================================
        # COMPLETE
        # ----------------------------------------------------
        # `status` records that the worker finished — pipeline-wise
        # we're done.  But `review_status` is the human-facing axis:
        # a fresh translation must sit in IN_REVIEW until a person
        # signs off (manually via /review-status or /certify).  This
        # is what powers the "Awaiting review" tab on the dashboard
        # and Projects pages; previously we left review_status at
        # the DRAFT default, so projects skipped review entirely and
        # showed up as Delivered immediately.
        # ====================================================
        project.progress_percent = 100
        project.status = ProjectStatus.COMPLETED
        # Don't downgrade if someone has already certified it (e.g.
        # a manual flip while the job was running).
        if (project.review_status or "DRAFT") == "DRAFT":
            project.review_status = "IN_REVIEW"

        db.commit()

        safe_broadcast(
            project_id,
            100,
            "IN_REVIEW",
        )

        # ====================================================
        # OUTPUT FILE — rebuild a layout-preserving copy with the
        # translated text in place of the source.
        # ====================================================
        output_file = temp_dir / f"translated_{project.file_name}"

        try:
            pairs = []
            for s in segments:
                # Carry source_text into layout so rebuilders that produce
                # a side-by-side view (e.g. the IMAGE rebuild for ID/passport
                # translations) can render both columns.
                meta = dict(s.layout_meta or {})
                meta["source_text"] = s.source_text
                pairs.append((s.translated_text or s.source_text, meta))
            written_path = rebuild_output(
                source_kind=source_kind,
                original_path=str(input_file),
                output_path=str(output_file),
                pairs=pairs,
                target_lang=target_lang,
            )
            output_to_upload = Path(written_path)
        except Exception as e:
            # Fall back to the original file so the user still gets a
            # download — but log loudly so this gets fixed.
            logger.exception(f"Layout-preserving rebuild failed: {e}")
            shutil.copyfile(input_file, output_file)
            output_to_upload = output_file

        output_s3_key = upload_file_to_s3(output_to_upload)

        project.output_file = output_s3_key

        db.commit()

        # ====================================================
        # CERTIFICATION
        # ====================================================
        try:
            cert_file = (
                temp_dir /
                f"{project.id}_certification.pdf"
            )

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

        if project:
            try:
                project.status = ProjectStatus.FAILED
                project.last_heartbeat = datetime.utcnow()

                db.commit()

                safe_broadcast(
                    str(project.id),
                    project.progress_percent or 0,
                    "FAILED"
                )

            except Exception:
                logger.exception(
                    "Failed marking project as FAILED"
                )

        # Re-raise so SQS worker knows this failed
        raise

    finally:
        if temp_dir:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )

        db.close()
