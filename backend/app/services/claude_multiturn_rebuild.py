"""Multi-turn Claude-authored rebuild.

This is the "match claude.ai chat" path. Instead of single-shot
(prompt → script → execute → done), we expose ONE tool to Claude
called `run_python_docx_code`. Claude writes code, we run it in the
sandbox, we read back the produced DOCX and return diagnostics
(page count, first body paragraphs, image count, table count,
forbidden-string flags, traceback if any). Claude can SEE its own
output and iterate — exactly the workflow claude.ai uses behind
the scenes for "make me a Word doc that matches this PDF".

Each rebuild call may consume 3–8 turns and 100k+ tokens. We accept
that cost because the alternative (single-shot prompt engineering)
has hit a quality ceiling.

Public entry point:
    author_rebuild_docx_multiturn(pdf_bytes, source_lang, target_lang,
                                  model=..., max_turns=6) -> bytes
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Initial prompt for the loop's first turn. Much shorter than the
# single-shot prompt because we expect Claude to iterate based on
# what its code actually produces — not to nail it in one go.
# ----------------------------------------------------------------
_INITIAL_PROMPT = """\
You are translating a document and producing a Microsoft Word
(.docx) file that preserves the source's visual layout.

WORKFLOW
========
You have one tool: `run_python_docx_code`. You call it with a
complete python-docx script. We run the script in a sandbox and
return diagnostics: file size, page count, first ~20 body
paragraphs, image count, table count, forbidden-string flags,
and any traceback. You then iterate — fix whatever doesn't match
the source, call the tool again, repeat until the output matches.

When the output looks correct (no forbidden-string warnings, the
content matches the source, layout looks right), STOP responding
and we'll take whatever the last successful run produced.

REQUIREMENTS
============
  * Translate from {source_lang} into {target_lang}.
  * Save the finished DOCX to exactly: r"{output_path}"
  * A4 page size (Cm(21) × Cm(29.7)), 2cm margins.
  * Body font 11pt minimum. Match the source's bold pattern —
    do NOT bold body paragraphs, two-label rows, or all-caps
    centered statements unless the source itself uses bold there.
  * Tables: borderless. Set tblBorders to nil on every table.
    Set width per column with `t.columns[i].width = Cm(N)`.
  * Two-label rows (e.g. "Cert. No. X" + "Student ID Y"): keep
    on ONE paragraph using a right-aligned tab stop at Cm(17).
  * Source-PDF images live at ./images/ (filenames provided
    below). Insert with `doc.add_picture("images/X.png", width=Cm(N))`
    using these sizes: crest 2.5cm, logo 3cm, seal/stamp 3cm,
    signature 5cm, photo 3cm. NEVER stretch a small image past
    its sizing budget.
  * FORBIDDEN: a CERTIFIED TRANSLATION / "I hereby certify" /
    "Translator: <email>" / "Signature: ___" block anywhere in
    your output. ALSO FORBIDDEN: any "Note: This is a translation
    of the original..." / "This document is a translation of..."
    sentence at the bottom — DO NOT add one. The certification
    page is appended by our wrapper AFTER your translation. Your
    job is the translation body only. Stop when the source's
    last paragraph is translated.
  * NO INLINE IMAGES ANYWHERE IN THE TRANSLATION BODY.
    Do NOT call doc.add_picture() at all. Do NOT insert a
    crest, logo, signature, seal, stamp, photo, QR code,
    or any other image — even if filenames are listed
    below. The wrapper embeds the FULL source PDF pages
    BEFORE your body, so the original crest / signature /
    seal / stamp are all preserved in their proper
    high-fidelity form on the source pages. Your translation
    is TEXT-ONLY.
      - Masthead: institution name typed in 12-14pt bold.
      - Signature block: officer name typed in normal
        weight, no signature image, no seal image.
      - Stamps / seals / QR codes: omit entirely from your
        body.
    This is the user's explicit instruction. Adding inline
    images produces blurry tiny rectangles that look
    broken — the source pages already show the originals
    at full quality.

EXTRACTED IMAGES (in ./images/)
===============================
{image_list}

EXTRACTED TABLES (use these JSON values verbatim for any data
table in your output)
===============================
{table_list}

Begin by writing the first version of the script and calling
`run_python_docx_code` with it. After each tool result, fix what
needs fixing.
"""


_TOOL_DEFINITION = {
    "name": "run_python_docx_code",
    "description": (
        "Run a Python script using python-docx in a sandbox. The "
        "script must save its output DOCX to the OUTPUT_PATH "
        "given in the prompt. Returns diagnostics: success, file "
        "size, page count, first ~20 body paragraphs, image count, "
        "table count, forbidden-string flags, and traceback (if "
        "the script failed). Use the diagnostics to verify the "
        "output matches the source and call this tool again with "
        "a fixed script if anything looks wrong."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Complete python-docx Python 3 script. Must "
                    "save to OUTPUT_PATH and not touch network/"
                    "subprocess modules."
                ),
            },
        },
        "required": ["code"],
    },
}


# ----------------------------------------------------------------
# Sandbox execution helpers (delegated to the existing single-shot
# service so we share the same hardened preamble).
# ----------------------------------------------------------------

def _run_in_sandbox(code: str, output_path: str, timeout_seconds: int = 180) -> tuple[bool, str, bytes]:
    """Run `code` in the existing sandbox. Returns
    (success, traceback_or_empty, docx_bytes_or_empty)."""
    try:
        from app.services.claude_authored_rebuild import (
            _run_script_in_sandbox,
            _validate_script,
            _strip_code_fence,
        )
    except Exception as e:
        return (False, f"Sandbox import error: {e}", b"")

    try:
        stripped = _strip_code_fence(code)
        _validate_script(stripped, output_path)
        docx_bytes = _run_script_in_sandbox(
            stripped, output_path=output_path, timeout_seconds=timeout_seconds
        )
        return (True, "", docx_bytes)
    except Exception as e:
        # Try to surface the underlying subprocess stderr if present.
        msg = str(e)
        return (False, msg, b"")


# ----------------------------------------------------------------
# DOCX inspection: produce a structured diagnostic that Claude can
# read after each tool call.
# ----------------------------------------------------------------

_FORBIDDEN_PATTERNS = [
    re.compile(r"\bCERTIFIED\s+TRANSLATION\b", re.I),
    re.compile(r"\bI\s+hereby\s+certify\b", re.I),
    re.compile(r"^\s*Translator\s*:\s*\S+@\S+", re.I | re.M),
    re.compile(r"^\s*Signature\s*:\s*_+", re.I | re.M),
    re.compile(r"this\s+translation\s+is\s+accurate\s+and\s+complete", re.I),
    # Translator's note variants — user explicitly wants these gone.
    re.compile(r"\bNote\s*:\s*This\s+(is|document)\s+(an|a)?\s*\w*\s*translation\b", re.I),
    re.compile(r"\bThis\s+document\s+is\s+(an|a)\s+\w+\s+translation\s+of\s+the\s+original\b", re.I),
]


def _inspect_docx(docx_bytes: bytes) -> dict:
    """Return a structured report describing the DOCX so Claude can
    judge whether it matches the source."""
    if not docx_bytes:
        return {"error": "DOCX bytes are empty"}

    try:
        import zipfile
        from xml.etree import ElementTree as ET
    except Exception as e:
        return {"error": f"stdlib import failed: {e}"}

    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    P_TAG = "{%s}p" % W_NS
    T_TAG = "{%s}t" % W_NS
    BR_TAG = "{%s}br" % W_NS
    TBL_TAG = "{%s}tbl" % W_NS
    DRAW_TAG = "{%s}drawing" % W_NS
    SECTPR_TAG = "{%s}sectPr" % W_NS

    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            doc_xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            media = [n for n in z.namelist() if n.startswith("word/media/")]
    except Exception as e:
        return {"error": f"DOCX parse failed: {e}"}

    try:
        root = ET.fromstring(doc_xml)
        body = root.find("{%s}body" % W_NS)
    except Exception as e:
        return {"error": f"document.xml parse failed: {e}"}

    # Paragraph texts.
    body_paragraphs = []
    if body is not None:
        for p in body.iter(P_TAG):
            txt = "".join(t.text or "" for t in p.iter(T_TAG)).strip()
            if txt:
                body_paragraphs.append(txt)

    # Page count estimate: 1 + (page breaks) + (section breaks of type nextPage).
    page_break_count = sum(
        1 for br in root.iter(BR_TAG)
        if br.get("{%s}type" % W_NS) == "page"
    )
    section_count = sum(1 for _ in root.iter(SECTPR_TAG))
    page_count_estimate = max(1, page_break_count + max(1, section_count) - 1)

    # Tables.
    tables = list(root.iter(TBL_TAG))

    # Drawings (images).
    drawings = list(root.iter(DRAW_TAG))

    # Forbidden-string scan.
    full_text = "\n".join(body_paragraphs)
    forbidden_hits = [
        pat.pattern for pat in _FORBIDDEN_PATTERNS if pat.search(full_text)
    ]

    report = {
        "success": True,
        "file_size_bytes": len(docx_bytes),
        "page_count_estimate": page_count_estimate,
        "paragraph_count": len(body_paragraphs),
        "first_paragraphs": body_paragraphs[:20],
        "last_paragraphs": body_paragraphs[-5:] if len(body_paragraphs) > 20 else [],
        "table_count": len(tables),
        "image_count": len(drawings),
        "media_files": media,
        "forbidden_string_hits": forbidden_hits,
    }

    # Practical warnings — turn obvious problems into something
    # Claude reads as "fix this".
    warnings = []
    if forbidden_hits:
        warnings.append(
            "Your output contains a CERTIFIED TRANSLATION / certification "
            "block. Remove it — the wrapper appends the real cert AFTER."
        )
    if page_count_estimate > 4:
        warnings.append(
            f"Output is {page_count_estimate} pages — that may exceed the "
            "source page count. Tighten line spacing or font size."
        )
    if not media and len(drawings) > 0:
        warnings.append(
            "Drawings reference images but no media files exist in the "
            "zip. Use existing files in ./images/ via doc.add_picture()."
        )

    # Detect "tabular data rendered as a flat paragraph list" — a
    # common regression where Claude bypasses doc.add_table() and
    # emits each course code / name / grade / date as a separate
    # paragraph. Signature: 5+ consecutive short paragraphs where
    # most look like table cell values (course code, "Passed",
    # grade fractions, sector codes, dates).
    cell_like_count = 0
    consecutive_cell_runs = []
    current_run = 0
    cell_patterns = [
        re.compile(r"^\d{6,10}$"),                    # course code
        re.compile(r"^Passed$|^Failed$|^Approved$", re.I),
        re.compile(r"^\d{2}/\d{2}$"),                 # grade fraction
        re.compile(r"^\d+$"),                         # credits
        re.compile(r"^[A-Z]{2,4}/\d{1,3}$"),          # sector code
        re.compile(r"^\d{2}/\d{2}/\d{4}$"),           # date
        re.compile(r"^PDS\d-\d{4}$"),                 # didactic plan
    ]
    for p in body_paragraphs:
        is_cell = (
            len(p) < 60
            and any(pat.match(p) for pat in cell_patterns)
        )
        if is_cell:
            cell_like_count += 1
            current_run += 1
        else:
            if current_run >= 5:
                consecutive_cell_runs.append(current_run)
            current_run = 0
    if current_run >= 5:
        consecutive_cell_runs.append(current_run)

    if consecutive_cell_runs and len(tables) == 0:
        warnings.append(
            f"Your output renders tabular data as a flat paragraph "
            f"list ({sum(consecutive_cell_runs)} cell-like paragraphs in "
            f"{len(consecutive_cell_runs)} run(s)) instead of using "
            f"doc.add_table(). EVERY data table from EXTRACTED TABLES "
            f"MUST be a real Word table created with "
            f"doc.add_table(rows=N, cols=M) — read the HARD RULE in "
            f"the prompt and use that recipe. Re-emit the script with "
            f"a proper table."
        )

    if warnings:
        report["warnings"] = warnings

    return report


# ----------------------------------------------------------------
# Main loop.
# ----------------------------------------------------------------

def author_rebuild_docx_multiturn(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    *,
    model: Optional[str] = None,
    max_turns: int = 6,
    timeout_per_run_seconds: int = 180,
) -> bytes:
    """End-to-end multi-turn Claude-authored rebuild.

    Returns the bytes of the best DOCX produced across the loop.
    Raises RuntimeError if no successful run was ever produced.
    """
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise RuntimeError("anthropic SDK not installed") from e

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    # Reuse the image / table pre-extraction from the single-shot
    # service so we don't duplicate logic.
    try:
        from app.services.claude_authored_rebuild import (
            _extract_pdf_images,
            _extract_tables_via_vision,
            _format_image_list,
            _format_table_list,
            _strip_rotation_from_docx,
            _strip_layout_table_borders,
            _strip_inline_cert_blocks,
            _replace_image_placeholders,
            _strip_broken_image_drawings,
        )
    except Exception as e:
        raise RuntimeError(f"Helper import failed: {e}")

    out_dir = Path(tempfile.mkdtemp(prefix="claude_multiturn_"))
    output_path = str(out_dir / "rebuild.docx")

    # Pre-extract assets.
    # 1) Vision-based image-region cropper — high-DPI render +
    #    Claude Vision identifies crests/signatures/seals and
    #    returns bounding boxes. This is the claude.ai-parity
    #    approach. Try it first; if it returns 0 regions or
    #    fails, fall back to the legacy XObject-extraction +
    #    header/footer-strip method.
    images = []
    _vision_image_list_text = None
    try:
        from app.services.claude_vision_image_extractor import (
            extract_image_regions_via_vision,
            format_vision_image_list,
        )
        vision_manifest = extract_image_regions_via_vision(
            pdf_bytes, out_dir
        )
        if vision_manifest:
            images = [
                {
                    "kind": m["kind"],
                    "filename": m["filename"],
                    "page": m["page"],
                    "width_px": m["width_px"],
                    "height_px": m["height_px"],
                    "suggested_width_cm": m["suggested_width_cm"],
                    "description": m.get("description", ""),
                    "_vision_source": True,
                }
                for m in vision_manifest
            ]
            _vision_image_list_text = format_vision_image_list(
                vision_manifest
            )
    except Exception:
        logger.exception("Vision image extraction failed — falling back")

    if not images:
        try:
            images = _extract_pdf_images(pdf_bytes, out_dir)
        except Exception:
            logger.exception("Image pre-extraction failed — continuing")
            images = []
    try:
        tables = _extract_tables_via_vision(pdf_bytes)
    except Exception:
        logger.exception("Table pre-extraction failed — continuing")
        tables = []

    image_list_text = (
        _vision_image_list_text
        if _vision_image_list_text
        else _format_image_list(images)
    )
    initial_prompt = _INITIAL_PROMPT.format(
        source_lang=source_lang or "the source language",
        target_lang=target_lang,
        output_path=output_path,
        image_list=image_list_text,
        table_list=_format_table_list(tables),
    )

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": initial_prompt},
            ],
        }
    ]

    chosen_model = model or "claude-opus-4-6"
    last_good_docx: bytes = b""
    last_good_inspection: dict = {}

    for turn in range(1, max_turns + 1):
        logger.info(
            "Multi-turn rebuild: turn %d/%d (model=%s)",
            turn, max_turns, chosen_model,
        )
        try:
            resp = client.messages.create(
                model=chosen_model,
                max_tokens=16000,
                tools=[_TOOL_DEFINITION],
                messages=messages,
            )
        except Exception as e:
            logger.exception("Anthropic call failed on turn %d: %s", turn, e)
            # If we already have a working DOCX from an earlier turn,
            # return it. Otherwise re-raise.
            if last_good_docx:
                break
            raise

        # Find any tool_use blocks in the response.
        tool_use_blocks = []
        text_blocks = []
        for block in resp.content or []:
            btype = getattr(block, "type", None)
            if btype == "tool_use":
                tool_use_blocks.append(block)
            elif btype == "text":
                text_blocks.append(getattr(block, "text", "") or "")

        # Always append the assistant turn so the conversation context
        # is preserved for the next call.
        messages.append({"role": "assistant", "content": resp.content})

        stop_reason = getattr(resp, "stop_reason", None)
        logger.info(
            "Turn %d: stop_reason=%s, tool_use_blocks=%d, text_chars=%d, "
            "input_tokens=%d, output_tokens=%d",
            turn,
            stop_reason,
            len(tool_use_blocks),
            sum(len(t) for t in text_blocks),
            getattr(resp.usage, "input_tokens", -1),
            getattr(resp.usage, "output_tokens", -1),
        )

        if not tool_use_blocks:
            # Claude responded with text only. Treat that as "done".
            if text_blocks:
                logger.info(
                    "Claude finished without further tool calls. "
                    "Final text (first 200 chars): %s",
                    "\n".join(text_blocks)[:200],
                )
            break

        # Run each