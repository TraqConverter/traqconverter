"""Structured export wrapper.

Wraps the translated DOCX (whether it came from the Claude-authored
path or the user's WYSIWYG edits) in the canonical certified-
translation layout:

  [SOURCE PAGES — original PDF rendered as images, 1 page = 1 DOCX page]
  [TRANSLATED CONTENT — merged in from the authored / edited DOCX]
  [CERTIFICATION PAGE — translator + date stamp, optionally via the
   project's selected certification template with {{token}} expansion]

If the team has uploaded a company stamp in Settings, it lives in the
section footer so Word repeats it on every page.

This is invoked from `generate_docx` and `generate_pdf` in
`export_service.py` whenever the project has an authored DOCX or
edited HTML — so the visual edits go through the same wrapper as the
Claude-authored output.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Source PDF → images (one per page).
# ----------------------------------------------------------------

def _render_source_pages_as_images(pdf_path: Path, work_dir: Path) -> list:
    """Render each page of `pdf_path` to a PNG at ~2x resolution. Returns
    a list of paths in page order. Failures yield an empty list."""
    try:
        import fitz  # PyMuPDF
    except Exception:
        logger.warning("PyMuPDF not installed — source pages not embedded")
        return []

    pages_dir = work_dir / "source_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    out = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.warning("Couldn't open source PDF for embedding: %s", e)
        return []
    try:
        # 2x scale gives a crisper image at A4-print resolution without
        # blowing up the DOCX size too much.
        zoom = fitz.Matrix(2, 2)
        for page_num, page in enumerate(doc, start=1):
            try:
                pix = page.get_pixmap(matrix=zoom, alpha=False)
                img_path = pages_dir / f"source_p{page_num}.png"
                pix.save(str(img_path))
                out.append(img_path)
            except Exception as e:
                logger.warning("Failed to render source page %d: %s", page_num, e)
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return out


# ----------------------------------------------------------------
# Team stamp → section footer (so it repeats on every page).
# ----------------------------------------------------------------

def _install_stamp_in_footer(section, stamp_path: Path, alignment: str = "right"):
    """Insert the team stamp image into the section's footer. Word
    auto-replicates section footers on every page of that section, so
    the stamp shows up on every page without per-page code."""
    try:
        footer = section.footer
        # If the footer already has a paragraph, reuse it — otherwise add one.
        if footer.paragraphs:
            p = footer.paragraphs[0]
        else:
            p = footer.add_paragraph()

        # Clear any previous content
        for run in list(p.runs):
            run.text = ""

        align_map = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
        }
        p.alignment = align_map.get(alignment, WD_ALIGN_PARAGRAPH.RIGHT)

        run = p.add_run()
        # Stamps are typically ~3cm wide — keeps them clearly visible
        # in the footer without taking over the page.
        run.add_picture(str(stamp_path), width=Cm(3))
    except Exception:
        logger.exception("Failed to install team stamp in footer")


# ----------------------------------------------------------------
# Append the body of another DOCX into the current one.
# ----------------------------------------------------------------

def _append_body_from(src_doc: Document, dst_doc: Document):
    """Copy paragraphs and tables from `src_doc.body` into `dst_doc.body`,
    preserving formatting at the XML level.

    Trims any trailing empty paragraphs (so the merged body doesn't
    add a blank page before whatever comes next), and drops the
    trailing sectPr (page-size info — we keep dst's own).
    """
    src_body = src_doc.element.body

    # Materialize the children list, drop trailing sectPr + trailing
    # blank paragraphs.
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    T_TAG = "{%s}t" % W_NS
    BR_TAG = "{%s}br" % W_NS
    PICT_TAG = "{%s}pict" % W_NS
    DRAWING_TAG = "{%s}drawing" % W_NS

    def _is_empty_para(el):
        if el.tag.split("}")[-1] != "p":
            return False
        # Has any text run?
        for t in el.iter(T_TAG):
            if (t.text or "").strip():
                return False
        # Has any drawing / picture (image)?
        for _ in el.iter(DRAWING_TAG):
            return False
        for _ in el.iter(PICT_TAG):
            return False
        # Has any page break?
        for br in el.iter(BR_TAG):
            if br.get("{%s}type" % W_NS) == "page":
                return False
        return True

    children = list(src_body.iterchildren())
    # Drop trailing sectPr.
    while children and children[-1].tag.split("}")[-1] == "sectPr":
        children.pop()
    # Drop trailing empty paragraphs.
    while children and _is_empty_para(children[-1]):
        children.pop()

    dst_body = dst_doc.element.body
    for child in children:
        try:
            dst_body.append(deepcopy(child))
        except Exception:
            logger.warning(
                "Skipped a body element during merge (%s)",
                child.tag.split("}")[-1],
            )


# ----------------------------------------------------------------
# Certification page — uses the team's selected template if one is
# set, otherwise falls back to the hardcoded boilerplate.
# ----------------------------------------------------------------

def _append_certification(dst_doc: Document, project, user, work_dir: Path):
    """Append a certification block to the document. If the project has
    a `certification_template_id` set, that DOCX is downloaded,
    {{token}} substitutions are applied, and its body is appended.
    Otherwise we write a simple hardcoded affidavit."""
    user_email = getattr(user, "email", "") or ""

    # Single page break before the cert — _append_body_from already
    # trimmed any trailing blanks from the merged translated section,
    # so this gives us exactly one new page for the cert.
    dst_doc.add_page_break()

    # Try the template first.
    try:
        from app.services.cert_template_service import (
            build_substitution_values,
            substitute_in_docx,
        )
        from app.services.s3_service import generate_presigned_download_url
        from app.models.certification import Certification
        from app.database import SessionLocal
        import requests as _req

        template_id = getattr(project, "certification_template_id", None)
        if template_id:
            db = SessionLocal()
            try:
                cert = (
                    db.query(Certification)
                    .filter(Certification.id == template_id)
                    .first()
                )
                if cert and getattr(cert, "s3_key", None):
                    url = generate_presigned_download_url(cert.s3_key)
                    r = _req.get(url, timeout=15)
                    if r.ok:
                        team = None
                        try:
                            from app.models.team import Team
                            team = (
                                db.query(Team)
                                .filter(Team.id == project.team_id)
                                .first()
                            )
                        except Exception:
                            pass
                        values = build_substitution_values(
                            user=user, project=project, team=team, extra=None
                        )
                        templated_bytes = substitute_in_docx(r.content, values)
                        templated_doc = Document(BytesIO(templated_bytes))
                        _append_body_from(templated_doc, dst_doc)
                        return
            finally:
                db.close()
    except Exception:
        logger.exception(
            "Cert-template substitution failed — falling back to hardcoded cert"
        )

    # Hardcoded fallback.
    from datetime import datetime

    p = dst_doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("CERTIFIED TRANSLATION")
    r.bold = True
    r.font.size = Pt(14)

    dst_doc.add_paragraph("")
    dst_doc.add_paragraph(
        "I hereby certify that this translation is accurate and "
        "complete to the best of my knowledge and ability."
    )
    dst_doc.add_paragraph("")
    dst_doc.add_paragraph(f"Translator: {user_email}")
    dst_doc.add_paragraph(
        f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )
    dst_doc.add_paragraph("")
    dst_doc.add_paragraph("Signature: ____________________________")


# ----------------------------------------------------------------
# Main entry point.
# ----------------------------------------------------------------

def build_full_export_docx(
    translated_docx_bytes: bytes,
    project,
    user,
) -> BytesIO:
    """Compose the final export DOCX from a translated DOCX:

        [source pages as images]
        [translated content]
        [certification page]

    Team stamp (if configured) lives in the footer and repeats on
    every page.

    Returns a BytesIO containing the finished DOCX, positioned at 0.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="export_wrap_"))
    try:
        # 1) Start a fresh document with sensible margins.
        out = Document()
        section = out.sections[0]
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

        # 2) Team stamp into footer (repeats on every page automatically).
        try:
            from app.services.export_service import _resolve_team_stamp
            stamp_path, alignment = _resolve_team_stamp(project, work_dir)
            if stamp_path:
                _install_stamp_in_footer(section, Path(stamp_path), alignment)
        except Exception:
            logger.exception(
                "Team-stamp resolution failed — continuing without footer stamp"
            )

        # 3) Embed source PDF pages as images.
        source_added = False
        try:
            from app.services.s3_service import download_file_from_s3
            source_path = work_dir / (project.file_name or "source")
            try:
                download_file_from_s3(project.file_path, source_path)
            except Exception:
                source_path = None

            if (
                source_path
                and source_path.exists()
                and str(source_path).lower().endswith(".pdf")
            ):
                page_imgs = _render_source_pages_as_images(source_path, work_dir)
                for i, img in enumerate(page_imgs):
                    p = out.add_paragraph()
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run = p.add_run()
                    # 17 cm = A4 portrait width minus 2cm margins on each side.
                    run.add_picture(str(img), width=Cm(17))
                    if i < len(page_imgs) - 1:
                        out.add_page_break()
                if page_imgs:
                    source_added = True
                    # Single break before the translated section.
                    # _append_body_from drops trailing blanks from the
                    # merged content so we don't double up.
                    out.add_page_break()
        except Exception:
            logger.exception(
                "Source-page embedding failed — continuing without source pages"
            )

        # 4) Merge the translated content.
        try:
            translated_doc = Document(BytesIO(translated_docx_bytes))
            _append_body_from(translated_doc, out)
        except Exception:
            logger.exception("Translated-body merge failed")
            # Last-ditch: dump translated text into a paragraph so the
            # export at least carries the translation.
            out.add_paragraph(
                "Translation content could not be merged. Please contact support."
            )

        # 5) Certification page.
        try:
            _append_certification(out, project, user, work_dir)
        except Exception:
            logger.exception("Certification append failed")

        # 6) Serialize.
        buf = BytesIO()
        out.save(buf)
        buf.seek(0)
        logger.info(
            "Full export built: source_added=%s, size=%d bytes",
            source_added, len(buf.getvalue()),
        )
        return buf
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass
