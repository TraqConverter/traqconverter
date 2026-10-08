"""Structured export wrapper.

Wraps the translated DOCX (whether it came from the Claude-authored
path or the user's WYSIWYG edits) in the canonical certified-
translation layout:

  [SOURCE PAGES — original PDF rendered as images, 1 page = 1 DOCX page]
  [TRANSLATED CONTENT — the authored / edited DOCX itself, the base document]
  [CERTIFICATION PAGE — translator + date stamp, optionally via the
   project's selected certification template with {{token}} expansion]

The editor document carries its own page stamp. An older one gets the
team's stamp from Media (by target language) in every section footer of
the translation, so Word repeats it on every page.

This is invoked from `generate_docx` and `generate_pdf` in
`export_service.py` whenever the project has an authored DOCX or
edited HTML — so the visual edits go through the same wrapper as the
Claude-authored output.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
import shutil
import tempfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Emu, Pt

logger = logging.getLogger(__name__)






# The delivery PDF appends the original itself, so it asks for the export without the page images.
SKIP_SOURCE_PAGES: ContextVar[bool] = ContextVar("skip_source_pages", default=False)


def _render_source_pages_as_images(pdf_path: Path, work_dir: Path) -> list:
    """Render each page of `pdf_path` to a PNG at ~2x resolution. Returns
    a list of paths in page order. Failures yield an empty list."""
    try:
        import fitz
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






def _detect_source_page_orientation(source_path) -> str:
    """Return 'portrait' or 'landscape' based on the source PDF's
    first-page aspect ratio. Defaults to portrait on any error so
    we never break existing behavior.
    """
    try:
        import fitz  # type: ignore
        try:
            d = fitz.open(str(source_path))
            try:
                if len(d) == 0:
                    return "portrait"
                r = d[0].rect
                return "landscape" if r.width > r.height else "portrait"
            finally:
                d.close()
        except Exception:
            pass
    except Exception:
        pass
    try:
        import pypdf
        r = pypdf.PdfReader(str(source_path))
        if not r.pages:
            return "portrait"
        box = r.pages[0].mediabox
        w = float(box.width)
        h = float(box.height)
        return "landscape" if w > h else "portrait"
    except Exception:
        return "portrait"


def _copy_missing_styles(src_doc: Document, dst_doc: Document, children) -> None:
    """Bring over paragraph/run styles the merged body uses but the destination lacks (e.g. the certification page break)."""
    try:
        by_id = {s.get(qn("w:styleId")): s for s in src_doc.styles.element.findall(qn("w:style"))}
        queue = [
            el.get(qn("w:val"))
            for child in children
            for el in child.iter(qn("w:pStyle"), qn("w:rStyle"), qn("w:tblStyle"))
        ]
        used = set()
        while queue:
            sid = queue.pop()
            if sid in by_id and sid not in used:
                used.add(sid)
                based = by_id[sid].find(qn("w:basedOn"))
                if based is not None:
                    queue.append(based.get(qn("w:val")))
        dst_styles = dst_doc.styles.element
        have = {s.get(qn("w:styleId")) for s in dst_styles.findall(qn("w:style"))}
        for sid, style in by_id.items():
            if sid in used and sid not in have:
                dst_styles.append(deepcopy(style))
    except Exception:
        logger.warning("Couldn't copy styles into the export", exc_info=True)


def _append_body_from(src_doc: Document, dst_doc: Document):
    """Copy paragraphs and tables from `src_doc.body` into `dst_doc.body`,
    preserving formatting at the XML level.

    Trims any trailing empty paragraphs (so the merged body doesn't
    add a blank page before whatever comes next), and drops the
    trailing sectPr (page-size info — we keep dst's own).
    """
    src_body = src_doc.element.body



    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    T_TAG = "{%s}t" % W_NS
    BR_TAG = "{%s}br" % W_NS
    PICT_TAG = "{%s}pict" % W_NS
    DRAWING_TAG = "{%s}drawing" % W_NS

    def _is_empty_para(el):
        if el.tag.split("}")[-1] != "p":
            return False

        for t in el.iter(T_TAG):
            if (t.text or "").strip():
                return False

        for _ in el.iter(DRAWING_TAG):
            return False
        for _ in el.iter(PICT_TAG):
            return False

        for br in el.iter(BR_TAG):
            if br.get("{%s}type" % W_NS) == "page":
                return False
        return True

    children = list(src_body.iterchildren())

    while children and children[-1].tag.split("}")[-1] == "sectPr":
        children.pop()

    while children and _is_empty_para(children[-1]):
        children.pop()

    dst_body = dst_doc.element.body













    final_sectpr = None
    for ch in list(dst_body.iterchildren()):
        if ch.tag.split("}")[-1] == "sectPr":
            final_sectpr = ch

    R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    EMBED_ATTR = "{%s}embed" % R_NS
    try:
        from docx.opc.constants import RELATIONSHIP_TYPE as _RT
    except Exception:
        _RT = None

    src_part = src_doc.part
    dst_part = dst_doc.part
    rid_map = {}
    images_copied = 0
    for child in children:
        for drawing in child.iter(DRAWING_TAG):
            for el in drawing.iter():
                rid = el.get(EMBED_ATTR)
                if not rid or rid in rid_map:
                    continue
                try:
                    related = src_part.related_parts.get(rid)
                except Exception:
                    related = None
                if related is None:
                    continue
                try:
                    if _RT is not None:
                        new_rid = dst_part.relate_to(related, _RT.IMAGE)
                    else:
                        new_rid = dst_part.relate_to(
                            related,
                            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                        )
                    rid_map[rid] = new_rid
                    images_copied += 1
                except Exception:
                    logger.warning(
                        "Failed to re-register image rel %s during merge", rid
                    )

    _copy_missing_styles(src_doc, dst_doc, children)

    # Hyperlinks point at relationships of the source part; recreate them on the destination.
    HYPERLINK_TAG = "{%s}hyperlink" % W_NS
    RID_ATTR = "{%s}id" % R_NS
    link_map = {}
    for child in children:
        for link in child.iter(HYPERLINK_TAG):
            rid = link.get(RID_ATTR)
            if not rid or rid in link_map:
                continue
            rel = src_part.rels.get(rid)
            if rel is None or not rel.is_external:
                continue
            link_map[rid] = dst_part.relate_to(rel.target_ref, rel.reltype, is_external=True)

    if images_copied:
        logger.info(
            "Carried over %d image(s) from authored DOCX into wrapper",
            images_copied,
        )

    docpr_tag = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
    docpr_ids = [0]
    for el in dst_body.iter(docpr_tag):
        try:
            docpr_ids.append(int(el.get("id", "0")))
        except ValueError:
            pass
    next_docpr = max(docpr_ids) + 1

    for child in children:
        try:
            copied = deepcopy(child)
            if rid_map:
                for el in copied.iter():
                    rid = el.get(EMBED_ATTR)
                    if rid and rid in rid_map:
                        el.set(EMBED_ATTR, rid_map[rid])
            for link in copied.iter(HYPERLINK_TAG):
                rid = link.get(RID_ATTR)
                if rid in link_map:
                    link.set(RID_ATTR, link_map[rid])
                elif rid:
                    del link.attrib[RID_ATTR]
            # Word rejects files whose drawings share an id with the wrapper's own pictures.
            for el in copied.iter(docpr_tag):
                el.set("id", str(next_docpr))
                next_docpr += 1
            if final_sectpr is not None:
                final_sectpr.addprevious(copied)
            else:
                dst_body.append(copied)
        except Exception:
            logger.warning(
                "Skipped a body element during merge (%s)",
                child.tag.split("}")[-1],
            )







def _append_certification(dst_doc: Document, project, user, work_dir: Path):
    """Append a certification block to the document. If the project has
    a `certification_template_id` set, that DOCX is downloaded,
    {{token}} substitutions are applied, and its body is appended.
    Otherwise we write a simple hardcoded affidavit."""
    user_email = getattr(user, "email", "") or ""




    try:
        from app.database import SessionLocal
        from app.services import cert_page, docx_certification
        from app.services.docx_blocks import strip_blocks

        db = SessionLocal()
        try:
            cert = cert_page.template_for(db, project)
            if cert is not None and cert_page.is_docx(cert):
                content = cert_page.content_for_project(db, project, user, cert_page.load_bytes(cert))
                page = strip_blocks(docx_certification.standalone(content))
                # The page's first paragraph already starts a new page.
                _append_body_from(Document(BytesIO(page)), dst_doc)
                return
        finally:
            db.close()
    except Exception:
        logger.exception(
            "Cert-template page failed — falling back to hardcoded cert"
        )

    dst_doc.add_page_break()

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






def _w_el(tag: str, **attrs):
    from docx.oxml import OxmlElement

    el = OxmlElement(f"w:{tag}")
    for name, value in attrs.items():
        el.set(qn(f"w:{name}"), str(value))
    return el


def _source_page_sectpr(page_w, page_h, margin):
    sect = _w_el("sectPr")
    sect.append(_w_el("pgSz", w=int(page_w.twips), h=int(page_h.twips), **({"orient": "landscape"} if page_w > page_h else {})))
    m = int(margin.twips)
    sect.append(_w_el("pgMar", top=m, right=m, bottom=m, left=m, header=0, footer=0, gutter=0))
    sect.append(_w_el("cols", space=720))
    return sect


def _source_image_width(img_path: Path, max_w, max_h):
    try:
        from PIL import Image

        with Image.open(img_path) as im:
            w, h = im.size
        return Emu(int(min(max_w, max_h * w / max(1, h))))
    except Exception:
        return max_w


def _prepend_source_pages(doc: Document, page_imgs: list, landscape: bool) -> None:
    """One section per original page, ahead of the translation, which keeps its own page setup, header and footer.

    These sections reference no header or footer, so the original's pages print without them.
    """
    page_w, page_h = (Cm(29.7), Cm(21)) if landscape else (Cm(21), Cm(29.7))
    margin = Cm(1)
    max_w = page_w - 2 * margin
    # A little under the text height, so an image line never spills onto a blank page.
    max_h = page_h - 2 * margin - Cm(0.5)
    body = doc.element.body
    first = next((c for c in body.iterchildren() if c.tag != qn("w:sectPr")), None)
    first_sect = next(body.iter(qn("w:sectPr")), None)
    for img in page_imgs:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fmt = p.paragraph_format
        fmt.space_before = fmt.space_after = Pt(0)
        fmt.line_spacing = 1.0
        fmt.left_indent = fmt.right_indent = fmt.first_line_indent = Cm(0)
        p.add_run().add_picture(str(img), width=_source_image_width(Path(img), max_w, max_h))
        p._p.get_or_add_pPr().append(_source_page_sectpr(page_w, page_h, margin))
        if first is not None:
            first.addprevious(p._p)
    # The translation's first section followed nothing before; now it must still start on its own page.
    if page_imgs and first_sect is not None:
        kind = first_sect.find(qn("w:type"))
        if kind is not None:
            first_sect.remove(kind)


def build_full_export_docx(
    translated_docx_bytes: bytes,
    project,
    user,
    append_certification: bool = True,
) -> BytesIO:
    """Compose the final export DOCX from a translated DOCX:

        [source pages as images]
        [translated content]
        [certification page]

    The translation is the base document, so its styles, defaults, theme, settings, page setup,
    headers and footers reach the export and the PDF exactly as the editor shows them.

    Returns a BytesIO containing the finished DOCX, positioned at 0.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="export_wrap_"))
    try:
        from app.services import docx_page_stamp

        data = translated_docx_bytes
        # The editor document carries its own stamp, as the user placed (or removed) it.
        if not docx_page_stamp.is_marked(data):
            try:
                from app.services.docx_images import prepare_image
                from app.services.export_service import _resolve_team_stamp

                stamp_path, alignment = _resolve_team_stamp(project, work_dir)
                if stamp_path:
                    image = prepare_image(Path(stamp_path).read_bytes())
                    data = docx_page_stamp.add_export_stamp(data, image, alignment)
            except Exception:
                logger.exception("Team-stamp resolution failed — continuing without footer stamp")

        try:
            out = Document(BytesIO(data))
        except Exception:
            logger.exception("Translated document wouldn't open")
            out = Document()
            out.add_paragraph("Translation content could not be merged. Please contact support.")

        source_added = False
        try:
            from app.services.s3_service import download_file_from_s3
            from app.services.translation_processor import local_file_name

            source_path = work_dir / local_file_name(project.file_name)
            try:
                download_file_from_s3(project.file_path, source_path)
            except Exception:
                source_path = None

            if (
                not SKIP_SOURCE_PAGES.get()
                and source_path
                and source_path.exists()
                and str(source_path).lower().endswith(".pdf")
            ):
                page_imgs = _render_source_pages_as_images(source_path, work_dir)
                if page_imgs:
                    landscape = _detect_source_page_orientation(source_path) == "landscape"
                    _prepend_source_pages(out, page_imgs, landscape)
                    source_added = True
        except Exception:
            logger.exception(
                "Source-page embedding failed — continuing without source pages"
            )

        if append_certification:
            try:
                _append_certification(out, project, user, work_dir)
            except Exception:
                logger.exception("Certification append failed")

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
