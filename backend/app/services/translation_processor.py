import logging
import tempfile
import shutil
import os
import asyncio

import pytesseract




TESSERACT_PATH = os.getenv("TESSERACT_CMD")

if TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    logging.getLogger(__name__).info(
        f"Using Tesseract from ENV: {TESSERACT_PATH}"
    )
else:
    import shutil as system_shutil

    detected = system_shutil.which("tesseract")


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

from app.core.file_validation import local_file_name
from app.models.project import TranslationProject, ProjectStatus, is_dtp
from app.models.translation_segment import TranslationSegment
from app.database import SessionLocal
from app.services.s3_service import (
    download_file_from_s3,
    upload_file_to_s3
)
from app.services.ai_translation_service import translate_batch, translate_text
from app.services import tm_keys
from app.services import translation_memory_service as tm_service
from app.services.layout_translator import (
    extract_segments,
    rebuild_output,
)
from app.routers.ws import broadcast_progress
from app.services import ai_usage, job_progress, learning, notifications, project_files
from app.services.glossary_service import lang_key, language_name, project_source_language
from app.services.project_lifecycle import SAME_LANGUAGE_REASON, mark_project_failed
from app.dependencies.feature_guard import project_has_feature
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

from docx import Document
import fitz
from PIL import Image

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
TEMPLATE_FILL_TIMEOUT = 600





def safe_broadcast(project_id: str, progress: int, status: str, extra: dict | None = None):
    payload = {"progress": progress, "status": status, **(extra or {})}
    try:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(broadcast_progress(project_id, payload))
        except RuntimeError:
            asyncio.run(broadcast_progress(project_id, payload))
    except Exception as e:
        logger.warning(f"WebSocket broadcast failed: {e}")





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




    elif ext == ".docx":
        doc = Document(file_path)

        return "\n".join(
            [p.text for p in doc.paragraphs if p.text.strip()]
        )




    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()




    elif ext in [".jpg", ".jpeg", ".png"]:
        try:
            image = Image.open(file_path)


            image = image.convert("RGB")

            return pytesseract.image_to_string(image)

        except Exception as e:
            logger.error("Image OCR failed")
            raise Exception(f"OCR failed: {e}")

    else:
        raise Exception(f"Unsupported file type: {ext}")





def _start_template_fill(db, project, source_kind, source_bytes, source_text, terminology):
    """Submit the template fill for this project's kind of document, or return None when there's no template."""
    if source_kind not in ("PDF", "IMAGE") or not project_has_feature(db, project, "templates"):
        return None
    template = learning.find_template(db, project.team_id, project.doc_key, project.target_language)
    if not template:
        return None
    from app.services import template_fill
    from app.services.document_editor import _download

    args = dict(
        source_data=source_bytes,
        file_name=project.file_name,
        source_text=source_text,
        template_source=template.source_text or "",
        source_lang=project_source_language(project) or project.source_language,
        target_lang=project.target_language,
        terminology=terminology,
        instructions=project.ai_instructions or "",
    )
    template_key = template.s3_key

    def run():
        return template_fill.fill_from_template(template_docx=_download(template_key), **args)

    logger.info("Template fill starting (project=%s template=%s)", project.id, template.id)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="template-fill")
    future = pool.submit(ai_usage.bind(run, action="template_fill", project_id=project.id, team_id=project.team_id))
    pool.shutdown(wait=False)
    return template.id, future


def _finish_template_fill(db, project, job, temp_dir) -> bool:
    """Save the template-built document as the authored DOCX; False means use the normal rebuild."""
    if not job:
        return False
    template_id, future = job
    try:
        docx_bytes, stats = future.result(timeout=TEMPLATE_FILL_TIMEOUT)
    except Exception:
        logger.exception("Template fill failed; using the normal rebuild (project=%s)", project.id)
        return False
    from app.models.learning import DocumentTemplate
    from app.services import s3_service

    path = temp_dir / f"template_{project.id}.docx"
    path.write_bytes(docx_bytes)
    replaced = project.authored_docx_s3_key
    project.authored_docx_s3_key = s3_service.upload_file_to_s3(path)
    template = db.query(DocumentTemplate).filter(DocumentTemplate.id == template_id).first()
    if template:
        learning.mark_template_used(db, project, template)
    db.commit()
    project_files.delete_replaced(db, [replaced])
    logger.info("Built from template (project=%s template=%s stats=%s)", project.id, template_id, stats)
    return True


def _stop_if_already_in_target(db, project) -> bool:
    """An auto-detected source in the target language fails with a full refund before any translation call."""
    if is_dtp(project) or lang_key(project.source_language):
        return False
    detected = (project.doc_profile or {}).get("source_language")
    # Only a detection that maps to a known language counts; anything unclear translates as usual.
    src = tm_keys.family(detected)
    if not src or src != tm_keys.family(project.target_language):
        return False
    mark_project_failed(db, project, SAME_LANGUAGE_REASON.format(language_name(lang_key(detected))))
    db.commit()
    logger.info("Project %s is already in %s; stopped before translation", project.id, detected)
    safe_broadcast(str(project.id), project.progress_percent or 0, project.status.value)
    return True



def _image_to_pdf(data: bytes, file_name: str) -> bytes:
    img = fitz.open(stream=data, filetype=Path(file_name).suffix.lstrip(".").lower() or "png")
    try:
        return img.convert_to_pdf()
    finally:
        img.close()


@ai_usage.project_task("translation")
def process_translation_job(project_id: str):
    logger.info(f"Worker starting processing for {project_id}")

    db: Session = SessionLocal()
    temp_dir = None
    project = None
    progress_scope = ExitStack()

    try:
        project_uuid = UUID(project_id)

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_uuid
        ).first()

        if not project:
            raise Exception("Project not found")




        project.status = ProjectStatus.PROCESSING
        project.progress_percent = 0
        project.progress_stage = job_progress.READING
        project.progress_detail = job_progress.STAGE_LABELS[job_progress.READING]
        project.stage_started_at = datetime.utcnow()
        project.translated_segments = 0
        project.failure_reason = None
        replaced_authored = project.authored_docx_s3_key
        project.authored_docx_s3_key = None
        project.template_id = None
        project.edited_html = None
        project.rebuild_error = None
        project.last_heartbeat = datetime.utcnow()

        db.commit()
        # Nothing reads the previous run's document once it's cleared, unless a saved version still holds it.
        project_files.delete_replaced(db, [replaced_authored])

        safe_broadcast(project_id, 0, "PROCESSING", {"stage": project.progress_stage, "detail": project.progress_detail})
        progress = job_progress.ProjectProgress(db, project, safe_broadcast)
        progress_scope.enter_context(job_progress.bind(progress))




        temp_dir = Path(tempfile.mkdtemp())

        input_file = temp_dir / local_file_name(project.file_name)

        download_file_from_s3(
            project.file_path,
            input_file
        )




        source_kind, extracted = extract_segments(str(input_file))

        if not extracted:
            raise Exception("No text extracted from file")

        project.source_kind = source_kind
        db.commit()

        source_bytes = input_file.read_bytes()
        source_text = "\n".join(item.text or "" for item in extracted)
        dtp = is_dtp(project)
        # Resolved once here and cached on the project for the rest of the job.
        has_templates = project_has_feature(db, project, "templates") and not dtp
        # The profile picks the template and detects an "auto" source language; otherwise it's skipped.
        if has_templates or not lang_key(project.source_language):
            learning.profile_project(db, project, source_bytes, source_text)
        if _stop_if_already_in_target(db, project):
            return
        if dtp:
            # An editable copy stays in the source language and uses no memory, glossary or template.
            project.target_language = project_source_language(project) or project.source_language
            db.commit()
            terminology, template_job = "", None
        else:
            terminology = tm_service.with_memory(db, project, learning.team_terminology(db, project, source_text), source_text)
            # The template fill runs next to segment translation so neither waits for the other.
            template_job = _start_template_fill(db, project, source_kind, source_bytes, source_text, terminology)




        db.query(TranslationSegment).filter(
            TranslationSegment.project_id == project_uuid
        ).delete()

        db.commit()




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




        source_lang = project.source_language or "English"
        target_lang = project.target_language or "Spanish"
        if dtp:
            source_lang = target_lang = project.target_language
            for seg in segments:
                seg.translated_text = seg.source_text
            project.translated_segments = len(segments)
            db.commit()









        use_tm = bool(getattr(project, "use_tm", True)) and not dtp
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
                tm_map = tm_service.exact_map(db, project, [seg.source_text for seg in segments])
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
            cached = tm_map.get(tm_keys.normalise_text(seg.source_text))
            if cached:
                seg.translated_text = cached
                seg.tm_pct = 100
                project.translated_segments += 1
                tm_hit_count += 1
            else:
                miss_indices.append(idx)
                miss_texts.append(seg.source_text)

        if tm_hit_count:


            db.commit()
            progress(job_progress.TRANSLATING, project.translated_segments / max(project.total_segments, 1))
            logger.info(
                "TM fast path: %d/%d segments served from memory (%d%% of doc)",
                tm_hit_count,
                len(segments),
                int((tm_hit_count / max(len(segments), 1)) * 100),
            )




        texts = [] if dtp else miss_texts
        if texts:
            progress(job_progress.TRANSLATING, project.translated_segments / max(project.total_segments, 1))

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



            if len(translations) != len(batch):


                translations = (translations + [""] * len(batch))[: len(batch)]










            for j, translated in enumerate(translations):
                seg_idx = miss_indices[i + j]
                seg = segments[seg_idx]
                clean = (translated or "").strip()
                if not clean:
                    continue
                seg.translated_text = clean
                seg.tm_pct = 0
                project.translated_segments += 1

            db.commit()







            # The memory only takes the translator's text (editor saves and delivery), never these drafts.
            progress(job_progress.TRANSLATING, project.translated_segments / max(project.total_segments, 1))













        # Certified output can't ship with source text standing in for a translation.
        untranslated = [
            s.segment_index for s in segments
            if not (s.translated_text or "").strip() and any(ch.isalpha() for ch in (s.source_text or ""))
        ]
        if untranslated:
            raise RuntimeError(
                f"{len(untranslated)} of {len(segments)} segments could not be translated"
            )

        if project.batch_id and not dtp:
            from app.services import batch_terms

            batch_terms.record_from_segments(db, project, [(s.source_text, s.translated_text) for s in segments])





        progress(job_progress.REBUILDING, 0.0)
        output_file = temp_dir / f"translated_{input_file.name}"

        try:
            pairs = []
            for s in segments:



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


            raise RuntimeError(f"Layout-preserving rebuild failed: {e}") from e

        output_s3_key = upload_file_to_s3(output_to_upload)

        replaced_output = project.output_file
        project.output_file = output_s3_key

        db.commit()
        project_files.delete_replaced(db, [replaced_output])














        if template_job is not None:
            progress(job_progress.REBUILDING, 0.05, "Filling the saved template")
        used_template = _finish_template_fill(db, project, template_job, temp_dir)
        if dtp:
            # The editable copy is the layout rebuild; scans uploaded as images get one too.
            wants_authored = source_kind in ("PDF", "IMAGE")
        else:
            wants_authored = (
                source_kind == "PDF"
                and (getattr(project, "model", "") or "") == "claude-authored"
                and not used_template
            )
        if wants_authored:
            try:
                from app.services.claude_authored_rebuild import (
                    author_rebuild_docx,
                )

                logger.info(
                    "Authored rebuild starting (project=%s)", project_id
                )
                with open(input_file, "rb") as _pdf_in:
                    pdf_bytes = _pdf_in.read()
                if source_kind == "IMAGE":
                    pdf_bytes = _image_to_pdf(pdf_bytes, project.file_name or "")
                authored_bytes = author_rebuild_docx(
                    pdf_bytes=pdf_bytes,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    terminology=terminology,
                    instructions="" if dtp else project.ai_instructions or "",
                    reproduce=dtp,
                )
                authored_path = (
                    temp_dir / f"authored_{project.id}.docx"
                )
                with open(authored_path, "wb") as f:
                    f.write(authored_bytes)
                authored_key = upload_file_to_s3(authored_path)
                replaced = project.authored_docx_s3_key
                project.authored_docx_s3_key = authored_key
                db.commit()
                project_files.delete_replaced(db, [replaced])
                logger.info(
                    "Authored rebuild OK (project=%s key=%s size=%d)",
                    project_id, authored_key, len(authored_bytes),
                )
            except Exception:
                logger.exception(
                    "Authored rebuild failed — falling back to "
                    "segment-driven output (project=%s)",
                    project_id,
                )
                project.rebuild_error = "Claude layout rebuild failed; showing the segment-based layout"
                db.commit()





        progress(job_progress.FINISHING, 0.0)
        progress_scope.close()
        project.progress_percent = 100
        project.progress_stage = None
        project.progress_detail = None
        project.stage_started_at = None
        project.status = ProjectStatus.COMPLETED
        project.retention_from = datetime.utcnow()
        if (project.review_status or "DRAFT") == "DRAFT":
            project.review_status = "IN_REVIEW"
        notifications.translation_done(db, project)
        db.commit()
        safe_broadcast(project_id, 100, "IN_REVIEW")

        logger.info("Worker completed")

    except Exception:
        # The worker decides between retry and FAILED-with-refund.
        logger.exception("Processing failed for project %s", project_id)
        db.rollback()
        raise

    finally:
        progress_scope.close()
        if temp_dir:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )

        db.close()
