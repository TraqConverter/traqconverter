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
    for line in build_certification(getattr(project, "_export_user_email", "")):
        out.add_paragraph(line)
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

    buffer = BytesIO()
    out.save(buffer)
    buffer.seek(0)
    return buffer


def _try_layout_pdf_from_project(project):
    if project is None:
        return None
    output_key = getattr(project, "output_file", None)
    if not output_key:
        return None
    kind = getattr(project, "source_kind", "").upper()
    if kind not in ("PDF", "IMAGE"):
        return None

    try:
        from app.services.s3_service import generate_presigned_download_url
        import requests
        url = generate_presigned_download_url(output_key)
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"Couldn't fetch rebuilt PDF from S3: {e}")
        return None

    try:
        import fitz
        rebuilt = fitz.open(stream=r.content, filetype="pdf")
    except Exception as e:
        logger.warning(f"Rebuilt PDF wouldn't open: {e}")
        return None

    cert_buf = BytesIO()
    cert_doc = SimpleDocTemplate(cert_buf)
    styles = getSampleStyleSheet()
    cert_content = []
    for line in build_certification(getattr(project, "_export_user_email", "")):
        cert_content.append(Paragraph(line, styles["Normal"]))
        cert_content.append(Spacer(1, 10))
    cert_doc.build(cert_content)
    cert_buf.seek(0)

    try:
        cert_pdf = fitz.open(stream=cert_buf.getvalue(), filetype="pdf")
        cert_pdf.insert_pdf(rebuilt)
        out = BytesIO()
        cert_pdf.save(out)
        cert_pdf.close()
        rebuilt.close()
        out.seek(0)
        return out
    except Exception as e:
        logger.warning(f"Cert+rebuild merge failed: {e}")
        return None


def generate_docx(segments, user_email, project=None):
    if project is not None:
        try:
            project._export_user_email = user_email
        except Exception:
            pass
        layout_doc = _try_layout_docx_from_project(project)
        if layout_doc is not None:
            return layout_doc

    doc = Document()
    for line in build_certification(user_email):
        doc.add_paragraph(line)
    for seg in segments:
        if seg.translated_text:
            doc.add_paragraph(seg.translated_text)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def generate_pdf(segments, user_email, project=None):
    if project is not None:
        try:
            project._export_user_email = user_email
        except Exception:
            pass
        layout_pdf = _try_layout_pdf_from_project(project)
        if layout_pdf is not None:
            return layout_pdf

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    content = []
    for line in build_certification(user_email):
        content.append(Paragraph(line, styles["Normal"]))
        content.append(Spacer(1, 10))
    for seg in segments:
        if seg.translated_text:
            content.append(Paragraph(seg.translated_text, styles["Normal"]))
            content.append(Spacer(1, 10))
    doc.build(content)
    buffer.seek(0)
    return buffer
