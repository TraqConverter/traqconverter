"""Export service.

The translation processor rebuilds a layout-preserving copy of the source
file and uploads it to S3 (`project.output_file`). For exports we prefer
that rebuilt file because it visually resembles the original — table
boxes, ID-card layouts and certificate borders are preserved.

Only when the rebuild is missing (older projects, or a rebuild that
failed mid-flight) do we fall back to a flat paragraph stack.
"""
from io import BytesIO
from datetime import datetime
import logging

from docx import Document
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

logger = logging.getLogger(__name__)


# ==============================
# CERTIFICATION BLOCK
# ==============================

def build_certification(user_email: str):
    return [
        "CERTIFIED TRANSLATION",
        "",
        "I hereby certify that this translation is accurate and complete.",
        "",
        f"Translator: {user_email}",
        f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "----------------------------------------",
        "",
    ]


# ==============================
# Try to load the layout-preserving DOCX rebuilt by the worker.
# ==============================

def _try_layout_docx_from_project(project) -> BytesIO | None:
    """Return the rebuilt DOCX as a BytesIO, prepending the certification
    page. Returns None if there's no rebuilt file or it isn't a DOCX."""
    if project is None:
        return None
    output_key = getattr(project, "output_file", None)
    if not output_key:
        return None
    if getattr(project, "source_kind", "").upper() != "DOCX":
        return None

    try:
        from app.services.s3_service import generate_presigned_download_url
        import requests
        url = generate_presigned_download_url(output_key)
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"Couldn't fetch rebuilt DOCX from S3: {e}")
        return None

    try:
        rebuilt = Document(BytesIO(r.content))
    except Exception as e:
        logger.warning(f"Rebuilt DOCX wouldn't open: {e}")
        return None

    out = Document()
    # Document body first.
    for para in rebuilt.paragraphs:
        new_p = out.add_paragraph()
        new_p.style = para.style
        for run in para.runs:
            r = new_p.add_run(run.text)
            r.bold = run.bold
            r.italic = run.italic
            r.underline = run.underline
            if run.font and run.font.size:
                r.font.size = run.font.size
    for table in rebuilt.tables:
        new_table = out.add_table(rows=len(table.rows), cols=len(table.columns))
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                new_table.cell(ri, ci).text = cell.text

    # Certification block appended at the end.
    out.add_paragraph("")
    for line in build_certification(getattr(project, "_export_user_email", "")):
        out.add_paragraph(line)

    buffer = BytesIO()
    out.save(buffer)
    buffer.seek(0)
    return buffer


def _build_layout_pdf_live(segments, project):
    """Build the export PDF in the new STRUCTURED format:

        Page 1+      : original document (image or PDF) verbatim
        Pages N+     : clean structured translation
        Final page   : certification block (optional company logo)

    Replaces the old in-place overlay (which produced bilingual residue
    on image documents) with a professionally-typeset translation that
    preserves alignment, bold/italic emphasis, placeholders for
    non-text elements, and source page breaks.
    """
    if project is None or not segments:
        return None
    kind = (getattr(project, "source_kind", "") or "").upper()
    if kind not in ("PDF", "IMAGE"):
        return None

    file_key = getattr(project, "file_path", None)
    if not file_key:
        return None

    import os
    import tempfile
    from datetime import datetime
    from pathlib import Path
    from app.services.s3_service import generate_presigned_download_url
    from app.services.structured_translation_renderer import (
        render_structured_export,
    )
    import requests

    try:
        url = generate_presigned_download_url(file_key)
        r = requests.get(url, timeout=20)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"Couldn't fetch source from S3: {e}")
        return None

    tmp_dir = Path(tempfile.mkdtemp(prefix="traqexport_"))
    try:
        ext = (
            ".pdf"
            if kind == "PDF"
            else os.path.splitext(file_key)[1] or ".jpg"
        )
        src_path = tmp_dir / f"source{ext}"
        with open(src_path, "wb") as f:
            f.write(r.content)

        # Build (translated, layout) pairs from current segments.
        pairs = []
        for s in segments:
            if not s.translated_text or not s.translated_text.strip():
                continue
            meta = dict(s.layout_meta or {})
            meta["source_text"] = s.source_text
            pairs.append((s.translated_text, meta))

        if not pairs:
            return None

        # Resolve a company logo: per-user S3 logo first, then optional
        # global default from settings.
        logo_path = None
        user_logo_key = getattr(project, "_export_user_logo_key", None)
        if user_logo_key:
            try:
                from app.services.s3_service import (
                    generate_presigned_download_url as _gen_url,
                )
                logo_url = _gen_url(user_logo_key)
                lr = requests.get(logo_url, timeout=10)
                if lr.ok:
                    logo_ext = (
                        os.path.splitext(user_logo_key)[1].lower() or ".png"
                    )
                    user_logo_file = tmp_dir / f"logo{logo_ext}"
                    with open(user_logo_file, "wb") as f:
                        f.write(lr.content)
                    logo_path = str(user_logo_file)
            except Exception as e:
                logger.warning("Couldn't fetch user logo: %s", e)
        if not logo_path:
            try:
                from app.config import settings as _s
                cand = getattr(_s, "COMPANY_LOGO_PATH", None)
                if cand and os.path.isfile(cand):
                    logo_path = cand
            except Exception:
                logo_path = None

        translator_email = getattr(project, "_export_user_email", "") or ""

        project_meta = {
            "title": (
                getattr(project, "file_name", None)
                or "Certified Translation"
            ),
            "file_name": getattr(project, "file_name", None) or "",
            "source_language": getattr(project, "source_language", "") or "",
            "target_language": getattr(project, "target_language", "") or "",
            "translator_email": translator_email,
            "certification_date": datetime.utcnow().strftime(
                "%Y-%m-%d %H:%M UTC"
            ),
        }

        pdf_bytes = render_structured_export(
            source_kind=kind,
            original_path=str(src_path),
            pairs=pairs,
            project_meta=project_meta,
            company_logo_path=logo_path,
        )

        out = BytesIO()
        out.write(pdf_bytes)
        out.seek(0)
        return out
    except Exception as e:
        logger.warning(
            "Structured export rendering failed: %s", e, exc_info=True
        )
        return None
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def generate_docx(segments, user_email, project=None, user=None):
    if project is not None:
        try:
            project._export_user_email = user_email
            project._export_user_logo_key = (
                getattr(user, "logo_s3_key", None) if user else None
            )
        except Exception:
            pass
        layout_doc = _try_layout_docx_from_project(project)
        if layout_doc is not None:
            return layout_doc

    doc = Document()
    # Translated body first…
    for seg in segments:
        if seg.translated_text:
            doc.add_paragraph(seg.translated_text)
    # …then the certification block at the end.
    doc.add_paragraph("")
    for line in build_certification(user_email):
        doc.add_paragraph(line)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def generate_pdf(segments, user_email, project=None, user=None):
    if project is not None:
        try:
            project._export_user_email = user_email
            project._export_user_logo_key = (
                getattr(user, "logo_s3_key", None) if user else None
            )
        except Exception:
            pass
        # Always rebuild from the live segments so edits + approval
        # filtering are honoured. Falls back to the flat paragraph
        # render below if the live rebuild can't run.
        layout_pdf = _build_layout_pdf_live(segments, project)
        if layout_pdf is not None:
            return layout_pdf

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    content = []
    # Translated body first…
    for seg in segments:
        if seg.translated_text:
            content.append(Paragraph(seg.translated_text, styles["Normal"]))
            content.append(Spacer(1, 10))
    # …then the certification block at the end.
    content.append(Spacer(1, 20))
    for line in build_certification(user_email):
        content.append(Paragraph(line, styles["Normal"]))
        content.append(Spacer(1, 10))
    doc.build(content)
    buffer.seek(0)
    return buffer
