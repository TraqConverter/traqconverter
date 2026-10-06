"""The delivery package: translation (certification page included), then a copy of the original, as one PDF."""
from __future__ import annotations

import io
import logging
import re

from sqlalchemy.orm import Session

from app.services import cert_locale

logger = logging.getLogger(__name__)

ORDERS = ("translation_first", "original_first")
_A4 = (595.28, 841.89)
_IMAGE_MARGIN = 28.35  # 1 cm


class DeliveryError(Exception):
    """A problem the translator can act on; the message is shown to them."""


def delivery_filename(project) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", project.file_name or "") or "translation"
    stem = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", stem).strip() or "translation"
    return f"{stem} - translation.pdf"


def separator_language(docx_bytes: bytes, target_language: str | None) -> str:
    """The certification page's language when it can be told from its text, else the one it would be written in."""
    from app.services.docx_certification import page_text

    try:
        detected = cert_locale.detect_language(page_text(docx_bytes))
    except Exception:
        detected = None
    lang = detected or cert_locale.cert_language(target_language)
    return lang if lang in cert_locale.ORIGINAL_COPY else "en"


def translation_pdf(db: Session, project, user) -> tuple[bytes, str]:
    """(PDF of the translation export, separator language). Built from the same DOCX as Export DOCX."""
    from app.routers.export import render_export
    from app.services.export_service import _convert_docx_to_pdf
    from app.services.export_wrapper import SKIP_SOURCE_PAGES

    # The export normally opens with the original's pages; here the original goes at the end instead.
    token = SKIP_SOURCE_PAGES.set(True)
    try:
        docx_bytes = render_export(db, project, user, "docx").getvalue()
        lang = separator_language(docx_bytes, project.target_language)
        pdf = _convert_docx_to_pdf(docx_bytes)
        if not pdf:
            # Same fallback as Export PDF when LibreOffice isn't there.
            pdf = render_export(db, project, user, "pdf").getvalue()
    finally:
        SKIP_SOURCE_PAGES.reset(token)
    return pdf, lang


def _image_pages(data: bytes):
    import fitz
    from PIL import Image, ImageOps, ImageSequence

    img = Image.open(io.BytesIO(data))
    out = fitz.open()
    for frame in ImageSequence.Iterator(img):
        frame = ImageOps.exif_transpose(frame).convert("RGB")
        buf = io.BytesIO()
        frame.save(buf, "PNG")
        w, h = _A4 if frame.height >= frame.width else (_A4[1], _A4[0])
        page = out.new_page(width=w, height=h)
        box = fitz.Rect(_IMAGE_MARGIN, _IMAGE_MARGIN, w - _IMAGE_MARGIN, h - _IMAGE_MARGIN)
        page.insert_image(box, stream=buf.getvalue(), keep_proportion=True)
    return out


def original_pdf(project):
    """The original as a fitz document: PDFs as they are, images fitted to A4, DOCX converted like exports."""
    import fitz

    from app.services.document_editor import _download
    from app.services.export_service import _convert_docx_to_pdf
    from app.services.source_pages import source_kind

    kind = source_kind(project.file_name)
    if kind == "other":
        raise DeliveryError("The original's file type can't be added to a PDF.")
    try:
        data = _download(project.file_path)
    except Exception:
        logger.exception("Couldn't fetch the original (project=%s)", project.id)
        raise DeliveryError("Couldn't fetch the original document.")

    if kind == "image":
        try:
            return _image_pages(data)
        except Exception:
            logger.exception("Couldn't read the original image (project=%s)", project.id)
            raise DeliveryError("Couldn't read the original image.")
    if kind == "docx":
        converted = _convert_docx_to_pdf(data)
        if not converted:
            raise DeliveryError("Couldn't convert the original DOCX to PDF.")
        data = converted
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise DeliveryError("Couldn't read the original PDF.")
    if doc.needs_pass:
        doc.close()
        raise DeliveryError("The original PDF is password-protected, so it can't be attached.")
    return doc


def _add_separator(doc, lang: str) -> None:
    import fitz

    page = doc.new_page(width=_A4[0], height=_A4[1])
    box = fitz.Rect(56, _A4[1] / 2 - 20, _A4[0] - 56, _A4[1] / 2 + 40)
    page.insert_textbox(box, cert_locale.ORIGINAL_COPY[lang], fontname="helv", fontsize=16, align=fitz.TEXT_ALIGN_CENTER)


def merge(translation: bytes, original, lang: str, order: str, title: str) -> bytes:
    import fitz

    out = fitz.open()
    with fitz.open(stream=translation, filetype="pdf") as tr:
        if original is None:
            out.insert_pdf(tr)
        elif order == "original_first":
            _add_separator(out, lang)
            out.insert_pdf(original)
            out.insert_pdf(tr)
        else:
            out.insert_pdf(tr)
            _add_separator(out, lang)
            out.insert_pdf(original)
    out.set_metadata({"title": title, "creator": "OnlineDocTranslator", "producer": "OnlineDocTranslator"})
    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    return data


def build_delivery_pdf(db: Session, project, user, *, include_original: bool = True, order: str = "translation_first") -> bytes:
    if order not in ORDERS:
        raise DeliveryError("Unknown page order.")
    translation, lang = translation_pdf(db, project, user)
    original = original_pdf(project) if include_original else None
    try:
        return merge(translation, original, lang, order, delivery_filename(project))
    finally:
        if original is not None:
            original.close()
