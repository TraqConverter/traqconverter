"""Layout-preserving translation pipeline.

Why this exists
---------------
The previous pipeline collapsed all whitespace into single spaces, regex-split
the result into "sentences", and emitted a flat stack of paragraphs. The
"output_file" uploaded to S3 was literally a copy of the original, untouched.

This module replaces both halves:

1. `extract_segments(...)` returns segments **with layout metadata** so that:
   - PDF blocks keep their bbox/font/page so we can put the translation
     back at the same coordinates.
   - DOCX paragraphs/table cells keep their position in the document tree
     so we can rewrite each in place — preserving boxes, tables, headings.
   - Image documents (passports/IDs/scans) are OCR'd at word level via
     pytesseract `image_to_data` and grouped into lines with bounding
     boxes so the translation can be drawn on a copy of the image.

2. `rebuild_output(...)` consumes the translated segments + layout metadata
   and writes a NEW file in the same format that closely resembles the
   source — table cells stay table cells, ID-style boxes stay boxed, etc.

Both halves degrade gracefully when extraction can't pull layout info
(scanned PDFs without OCR data, exotic encodings, etc.) — they fall back
to the simple paragraph stack used by the export router.
"""
from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# Public segment shape used between extractor and rebuilder.
# ============================================================

@dataclass
class ExtractedSegment:
    text: str
    layout: dict[str, Any] = field(default_factory=dict)


# ============================================================
# Source kind detection
# ============================================================

def detect_source_kind(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return "PDF"
    if ext == ".docx":
        return "DOCX"
    if ext in (".jpg", ".jpeg", ".png"):
        return "IMAGE"
    if ext == ".txt":
        return "TXT"
    return "UNKNOWN"


# ============================================================
# EXTRACTORS
# ============================================================

def _extract_pdf(file_path: str) -> list[ExtractedSegment]:
    """Use PyMuPDF blocks. Each block becomes one segment.

    Block coords are stored so we can put the translation back at the
    same place when rebuilding the PDF.
    """
    import fitz

    out: list[ExtractedSegment] = []
    doc = fitz.open(file_path)
    try:
        for page_index, page in enumerate(doc):
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue  # skip image blocks for now
                # Concatenate spans → text per block, also pick up the
                # dominant font size and color from the first span so the
                # rewrite looks visually similar.
                lines = block.get("lines", [])
                texts: list[str] = []
                font_size = 11.0
                color = 0
                for line in lines:
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    if spans[0].get("size"):
                        font_size = float(spans[0]["size"])
                    if spans[0].get("color") is not None:
                        color = int(spans[0]["color"])
                    line_text = "".join(s.get("text", "") for s in spans)
                    if line_text.strip():
                        texts.append(line_text)
                text = "\n".join(texts).strip()
                if not text:
                    continue
                bbox = list(block.get("bbox", [0, 0, 0, 0]))
                out.append(
                    ExtractedSegment(
                        text=text,
                        layout={
                            "kind": "pdf_block",
                            "page": page_index,
                            "bbox": bbox,
                            "font_size": font_size,
                            "color": color,
                        },
                    )
                )
    finally:
        doc.close()

    # Fallback OCR if nothing extracted (scanned PDF).
    if not out:
        out = _extract_pdf_via_ocr(file_path)

    return out


def _extract_pdf_via_ocr(file_path: str) -> list[ExtractedSegment]:
    """Render each page and OCR with bounding boxes."""
    import fitz
    import pytesseract
    from PIL import Image

    out: list[ExtractedSegment] = []
    doc = fitz.open(file_path)
    try:
        for page_index, page in enumerate(doc):
            pix = page.get_pixmap()
            img = Image.frombytes(
                "RGB", [pix.width, pix.height], pix.samples
            )
            try:
                data = pytesseract.image_to_data(
                    img, output_type=pytesseract.Output.DICT
                )
            except Exception as e:
                logger.warning(f"OCR failed on page {page_index}: {e}")
                continue

            # Group by (block_num, par_num, line_num) → one segment per line
            lines: dict[tuple, dict] = {}
            n = len(data.get("text", []))
            for i in range(n):
                txt = (data["text"][i] or "").strip()
                if not txt:
                    continue
                key = (
                    data["block_num"][i],
                    data["par_num"][i],
                    data["line_num"][i],
                )
                entry = lines.setdefault(
                    key,
                    {
                        "words": [],
                        "x": int(data["left"][i]),
                        "y": int(data["top"][i]),
                        "right": int(data["left"][i] + data["width"][i]),
                        "bottom": int(data["top"][i] + data["height"][i]),
                    },
                )
                entry["words"].append(txt)
                entry["x"] = min(entry["x"], int(data["left"][i]))
                entry["y"] = min(entry["y"], int(data["top"][i]))
                entry["right"] = max(
                    entry["right"], int(data["left"][i] + data["width"][i])
                )
                entry["bottom"] = max(
                    entry["bottom"], int(data["top"][i] + data["height"][i])
                )

            for line_idx, info in enumerate(lines.values()):
                line_text = " ".join(info["words"]).strip()
                if not line_text:
                    continue
                out.append(
                    ExtractedSegment(
                        text=line_text,
                        layout={
                            "kind": "pdf_ocr_line",
                            "page": page_index,
                            "bbox": [
                                info["x"],
                                info["y"],
                                info["right"],
                                info["bottom"],
                            ],
                            "line": line_idx,
                        },
                    )
                )
    finally:
        doc.close()

    return out


def _extract_docx(file_path: str) -> list[ExtractedSegment]:
    """Walk paragraphs (top-level) and table cells in document order."""
    from docx import Document

    out: list[ExtractedSegment] = []
    doc = Document(file_path)

    # Top-level paragraphs
    for para_idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        out.append(
            ExtractedSegment(
                text=text,
                layout={
                    "kind": "docx_paragraph",
                    "para_index": para_idx,
                },
            )
        )

    # Tables — translate every cell, every paragraph inside the cell
    for tbl_idx, table in enumerate(doc.tables):
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                for cp_idx, cp in enumerate(cell.paragraphs):
                    text = cp.text.strip()
                    if not text:
                        continue
                    out.append(
                        ExtractedSegment(
                            text=text,
                            layout={
                                "kind": "docx_table_cell",
                                "table_index": tbl_idx,
                                "row": row_idx,
                                "col": col_idx,
                                "para_in_cell": cp_idx,
                            },
                        )
                    )

    return out


def _extract_image(file_path: str) -> list[ExtractedSegment]:
    """Word-level OCR with bounding boxes — perfect for IDs/passports.

    Each text line becomes a segment whose layout has the line's bbox so
    the rebuilder can paint the translated text into the same area.
    """
    import pytesseract
    from PIL import Image

    image = Image.open(file_path).convert("RGB")
    try:
        data = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT
        )
    except Exception as e:
        raise Exception(f"OCR failed: {e}")

    lines: dict[tuple, dict] = {}
    n = len(data.get("text", []))
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        entry = lines.setdefault(
            key,
            {
                "words": [],
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "right": int(data["left"][i] + data["width"][i]),
                "bottom": int(data["top"][i] + data["height"][i]),
            },
        )
        entry["words"].append(txt)
        entry["x"] = min(entry["x"], int(data["left"][i]))
        entry["y"] = min(entry["y"], int(data["top"][i]))
        entry["right"] = max(
            entry["right"], int(data["left"][i] + data["width"][i])
        )
        entry["bottom"] = max(
            entry["bottom"], int(data["top"][i] + data["height"][i])
        )

    out: list[ExtractedSegment] = []
    for line_idx, info in enumerate(lines.values()):
        line_text = " ".join(info["words"]).strip()
        if not line_text:
            continue
        out.append(
            ExtractedSegment(
                text=line_text,
                layout={
                    "kind": "image_line",
                    "page": 0,
                    "bbox": [info["x"], info["y"], info["right"], info["bottom"]],
                    "line": line_idx,
                },
            )
        )
    return out


def _extract_txt(file_path: str) -> list[ExtractedSegment]:
    """Plain text — preserve paragraph splits (blank-line separated)."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    out: list[ExtractedSegment] = []
    for idx, para in enumerate(raw.split("\n\n")):
        text = para.strip()
        if not text:
            continue
        out.append(
            ExtractedSegment(
                text=text,
                layout={"kind": "txt_paragraph", "para_index": idx},
            )
        )
    return out


def extract_segments(file_path: str) -> tuple[str, list[ExtractedSegment]]:
    """Return (source_kind, segments). Segments preserve enough metadata
    that rebuild_output can reconstruct a similar-looking file."""
    kind = detect_source_kind(file_path)
    if kind == "PDF":
        return kind, _extract_pdf(file_path)
    if kind == "DOCX":
        return kind, _extract_docx(file_path)
    if kind == "IMAGE":
        return kind, _extract_image(file_path)
    if kind == "TXT":
        return kind, _extract_txt(file_path)
    raise Exception(f"Unsupported file type for {file_path}")


# ============================================================
# REBUILDERS — produce a file that resembles the source.
# ============================================================

def _rebuild_pdf(
    original_path: str,
    output_path: str,
    pairs: list[tuple[str, dict[str, Any]]],
) -> None:
    """Open a copy of the original PDF, white-out each block, and draw the
    translation back into the same bbox at a similar font size. Tables,
    forms and ID-style boxed layouts stay intact because we only touch
    text rectangles — borders, images and the rest of the page are
    preserved by the original.
    """
    import fitz

    doc = fitz.open(original_path)
    try:
        for translated_text, layout in pairs:
            if not translated_text:
                continue
            kind = layout.get("kind")
            page_idx = layout.get("page", 0)
            bbox = layout.get("bbox")
            if bbox is None or page_idx >= len(doc):
                continue
            page = doc[page_idx]
            rect = fitz.Rect(*bbox)
            # Paint over the source text
            page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
            font_size = float(layout.get("font_size") or 11.0)
            color_int = int(layout.get("color") or 0)
            r = ((color_int >> 16) & 0xFF) / 255.0
            g = ((color_int >> 8) & 0xFF) / 255.0
            b = (color_int & 0xFF) / 255.0

            # Auto-shrink the font until the translation fits in the box.
            # PyMuPDF's insert_textbox returns a negative number when the
            # text overflows; loop down to a reasonable floor.
            for size in (font_size, font_size * 0.9, font_size * 0.8, font_size * 0.7, 6.0):
                rc = page.insert_textbox(
                    rect,
                    translated_text,
                    fontsize=size,
                    color=(r, g, b),
                    fontname="helv",
                    align=0,
                )
                if rc >= 0:
                    break
            else:
                logger.debug(
                    f"Translation didn't fit on page {page_idx} bbox {bbox}"
                )
        doc.save(output_path, garbage=4, deflate=True)
    finally:
        doc.close()


def _rebuild_docx(
    original_path: str,
    output_path: str,
    pairs: list[tuple[str, dict[str, Any]]],
) -> None:
    """Open the original DOCX, replace each paragraph/table-cell paragraph
    with its translation while keeping the run formatting (font, color,
    alignment) intact for visual similarity. Tables (boxes) survive
    because we never touch the table structure.
    """
    from docx import Document

    doc = Document(original_path)

    # Index the input pairs by their layout so we can look them up cheaply.
    by_para: dict[int, str] = {}
    by_cell: dict[tuple[int, int, int, int], str] = {}
    for translated, layout in pairs:
        kind = layout.get("kind")
        if kind == "docx_paragraph":
            by_para[int(layout.get("para_index", -1))] = translated
        elif kind == "docx_table_cell":
            by_cell[
                (
                    int(layout.get("table_index", -1)),
                    int(layout.get("row", -1)),
                    int(layout.get("col", -1)),
                    int(layout.get("para_in_cell", -1)),
                )
            ] = translated

    def _replace_paragraph_text(paragraph, new_text: str) -> None:
        """Keep the first run's formatting; drop any extra runs; set new text."""
        runs = paragraph.runs
        if not runs:
            paragraph.add_run(new_text)
            return
        runs[0].text = new_text
        for r in runs[1:]:
            r.text = ""

    for para_idx, para in enumerate(doc.paragraphs):
        if para_idx in by_para:
            _replace_paragraph_text(para, by_para[para_idx])

    for tbl_idx, table in enumerate(doc.tables):
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                for cp_idx, cp in enumerate(cell.paragraphs):
                    key = (tbl_idx, row_idx, col_idx, cp_idx)
                    if key in by_cell:
                        _replace_paragraph_text(cp, by_cell[key])

    doc.save(output_path)


def _rebuild_image(
    original_path: str,
    output_path: str,
    pairs: list[tuple[str, dict[str, Any]]],
) -> None:
    """Render translated text on top of a copy of the source image at the
    OCR-detected bounding boxes. Background is whitened first so the
    original wording isn't visible underneath. Output is PDF (so the
    box coordinates match the on-screen layout exactly)."""
    from PIL import Image, ImageDraw, ImageFont
    import fitz

    image = Image.open(original_path).convert("RGB").copy()
    draw = ImageDraw.Draw(image)

    # Try to load a system font; fall back to PIL default.
    def _font(size: int):
        for candidate in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ):
            if os.path.exists(candidate):
                try:
                    return ImageFont.truetype(candidate, size=size)
                except Exception:
                    continue
        return ImageFont.load_default()

    for translated, layout in pairs:
        if not translated:
            continue
        bbox = layout.get("bbox")
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        h = max(1, y1 - y0)
        w = max(1, x1 - x0)
        # White-out the source text.
        draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 255))
        # Pick a font size that fits the row height; PIL has no easy fit
        # primitive so we shrink until it fits horizontally too.
        size = max(6, int(h * 0.85))
        font = _font(size)
        while size > 6:
            try:
                tw = draw.textlength(translated, font=font)
            except Exception:
                tw = len(translated) * size * 0.6
            if tw <= w * 1.05:
                break
            size -= 1
            font = _font(size)
        draw.text((x0, y0 + max(0, (h - size) // 2)), translated, fill=(0, 0, 0), font=font)

    # Wrap the rendered image into a single-page PDF for consistent
    # downstream handling alongside PDF/DOCX outputs.
    img_bytes = io.BytesIO()
    image.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    pdf = fitz.open()
    pix = fitz.Pixmap(img_bytes.getvalue())
    page = pdf.new_page(width=pix.width, height=pix.height)
    page.insert_image(page.rect, pixmap=pix)
    pdf.save(output_path)
    pdf.close()


def _rebuild_txt(
    original_path: str,
    output_path: str,
    pairs: list[tuple[str, dict[str, Any]]],
) -> None:
    """Stitch translated paragraphs back together with blank-line separators
    in the original paragraph order."""
    by_idx: dict[int, str] = {}
    for translated, layout in pairs:
        if layout.get("kind") == "txt_paragraph":
            by_idx[int(layout.get("para_index", -1))] = translated
    if not by_idx:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(t for t, _ in pairs))
        return
    ordered = [by_idx[k] for k in sorted(by_idx.keys())]
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(ordered))


def rebuild_output(
    source_kind: str,
    original_path: str,
    output_path: str,
    pairs: list[tuple[str, dict[str, Any]]],
) -> str:
    """Produce a file at `output_path` that resembles `original_path` but
    with the source text replaced by translations. Returns the path that
    was actually written (may differ from the requested extension when we
    fall back, e.g. an image source becomes a PDF)."""
    if source_kind == "PDF":
        _rebuild_pdf(original_path, output_path, pairs)
        return output_path
    if source_kind == "DOCX":
        _rebuild_docx(original_path, output_path, pairs)
        return output_path
    if source_kind == "IMAGE":
        # Force a .pdf extension since we render the result as a PDF.
        new_path = os.path.splitext(output_path)[0] + ".pdf"
        _rebuild_image(original_path, new_path, pairs)
        return new_path
    if source_kind == "TXT":
        _rebuild_txt(original_path, output_path, pairs)
        return output_path
    raise Exception(f"Don't know how to rebuild {source_kind}")
