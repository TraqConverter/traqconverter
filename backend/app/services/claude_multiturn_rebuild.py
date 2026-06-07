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
# ---- Document-type classifier + adaptive prompt templates ----
#
# A previous version had a single _INITIAL_PROMPT optimised for
# certificates and letters. Tax forms (Italian Modello Redditi etc.)
# silently failed because Claude tried to satisfy the masthead /
# "institution name first" rule and ran out of tokens before getting
# to the form body. We now classify the document and feed a prompt
# that matches the layout family.
#
# Classification: a single Vision call on page 1 returns one of:
#   CERTIFICATE, FORM, LETTER, RECEIPT, CONTRACT, OTHER
# OTHER + LETTER fall back to the certificate prompt (closest match).

_CLASSIFY_PROMPT = (
    "Classify this document into exactly ONE of these categories. "
    "Respond with ONLY the category name in uppercase, no punctuation, "
    "no explanation.\n\n"
    "Categories:\n"
    "  CERTIFICATE  — diploma, transcript, citizenship cert, residence "
    "cert, marriage/birth/death cert, employment cert. Usually has a "
    "centered title, institutional masthead, a few key fields, a stamp "
    "and a signature.\n"
    "  FORM         — tax form (Modello Redditi, 1040), application form, "
    "registration form, government form with many numbered fields/cells "
    "and column codes (RA1, RN3, etc.) and grids of empty boxes.\n"
    "  LETTER       — letter, memo, official notice, correspondence with "
    "flowing paragraphs and a date/signature block.\n"
    "  RECEIPT      — receipt, invoice, payment confirmation, itemised "
    "list of charges with totals.\n"
    "  CONTRACT     — contract, agreement, terms-of-service with "
    "numbered clauses and signature lines.\n"
    "  OTHER        — anything else (book pages, articles, etc.).\n\n"
    "Look ONLY at the document's structure and visual layout — not "
    "the language. Reply with one word."
)


def _classify_document(pdf_bytes: bytes) -> str:
    """Use Claude Vision on page 1 to pick a layout family. Returns
    one of CERTIFICATE / FORM / LETTER / RECEIPT / CONTRACT / OTHER.

    On any failure returns CERTIFICATE (the safest backward-compatible
    default — the original prompt was tuned for certs).
    """
    try:
        import base64
        import anthropic  # type: ignore
        import fitz  # type: ignore  # pymupdf
    except Exception:
        return "CERTIFICATE"

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "CERTIFICATE"
    try:
        # Render page 1 at modest DPI so the classifier is fast.
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) == 0:
            return "CERTIFICATE"
        pix = doc[0].get_pixmap(dpi=120)
        png_bytes = pix.tobytes("png")
        doc.close()
        if len(png_bytes) > 4_500_000:
            # Re-render smaller if too big for the API.
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pix = doc[0].get_pixmap(dpi=80)
            png_bytes = pix.tobytes("png")
            doc.close()
        img_b64 = base64.standard_b64encode(png_bytes).decode("ascii")
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=os.getenv(
                "REBUILD_CLASSIFIER_MODEL", "claude-haiku-4-5-20251001"
            ),
            max_tokens=20,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": _CLASSIFY_PROMPT},
                    ],
                }
            ],
        )
        for block in resp.content or []:
            if getattr(block, "type", "") == "text":
                raw = (getattr(block, "text", "") or "").strip().upper()
                # Be lenient about extras.
                for cat in (
                    "CERTIFICATE", "FORM", "LETTER", "RECEIPT",
                    "CONTRACT", "OTHER",
                ):
                    if cat in raw:
                        logger.info(
                            "Document classified as %s", cat
                        )
                        return cat
        return "CERTIFICATE"
    except Exception:
        logger.exception("Document classifier failed — defaulting to CERTIFICATE")
        return "CERTIFICATE"

# ---- Exhaustive form-field extraction (FORM-only) --------------
#
# For tax forms / applications / structured forms, doing a generic
# vision pass and asking Claude to "extract tables" misses field
# labels that aren't in obvious grid rows (section headers,
# numbered checkboxes, free-text fields). This function asks
# Claude Vision to produce a flat JSON listing EVERY visible
# label, code, and value on the page. The JSON is then embedded
# in the FORM prompt as ground truth so the authoring step
# doesn't have to OCR.

_FORM_DUMP_PROMPT = (
    "You are looking at one page of a structured form (tax return, "
    "application, registration form, or similar). List every visible "
    "label, section code (RA1, RN3, etc.), column number (1..16), "
    "filled-in value (tax code, amount, percentage, date, ID), and "
    "section title.\n\n"
    "Output ONE JSON array. Each entry is an object with keys:\n"
    "  - 'kind'  : one of section_title, field_label, section_code, "
    "column_number, value, checkbox, instruction_note\n"
    "  - 'text'  : the verbatim text exactly as it appears on the form, "
    "in the source language\n"
    "  - 'group' : the form section this belongs to (e.g. 'QUADRO RA', "
    "'QUADRO RN', 'Header'). Use 'Header' for items above the first "
    "section.\n\n"
    "Be exhaustive — DO NOT skip cells just because they look empty. "
    "Empty value cells should appear as {'kind':'value','text':',00',"
    "'group':...}. Reply with ONLY the JSON array, no prose, no "
    "code fence."
)


def _extract_form_fields_via_vision(pdf_bytes: bytes) -> list:
    """Run an exhaustive form-field dump on every page. Returns a
    list of {'page': N, 'fields': [...]} dicts ready to embed in
    the FORM prompt. Empty list on any failure — the FORM prompt
    still works without this, just less reliably.
    """
    try:
        import base64
        import json as _json
        import anthropic  # type: ignore
        import fitz  # type: ignore
    except Exception:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    model = os.getenv("REBUILD_FORM_DUMP_MODEL", "claude-opus-4-6")
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return []

    pages_out = []
    try:
        client = anthropic.Anthropic(api_key=api_key)
        for page_idx in range(len(doc)):
            try:
                page = doc[page_idx]
                # Render at high DPI so small cells / fine print
                # are legible.
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
                png_bytes = pix.tobytes("png")
                if len(png_bytes) > 4_500_000:
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6))
                    png_bytes = pix.tobytes("png")
                img_b64 = base64.standard_b64encode(png_bytes).decode("ascii")
                resp = client.messages.create(
                    model=model,
                    max_tokens=6000,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": img_b64,
                                    },
                                },
                                {"type": "text", "text": _FORM_DUMP_PROMPT},
                            ],
                        }
                    ],
                )
                raw = ""
                for block in resp.content or []:
                    if getattr(block, "type", "") == "text":
                        raw += getattr(block, "text", "") or ""
                raw = raw.strip()
                # Strip optional code fences.
                if raw.startswith("```"):
                    raw = raw.lstrip("`")
                    if raw.lower().startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip("` \n")
                try:
                    fields = _json.loads(raw)
                except Exception:
                    # Try to salvage the array portion.
                    start = raw.find("[")
                    end = raw.rfind("]")
                    if start != -1 and end != -1 and end > start:
                        try:
                            fields = _json.loads(raw[start:end + 1])
                        except Exception:
                            fields = []
                    else:
                        fields = []
                if isinstance(fields, list) and fields:
                    pages_out.append({
                        "page": page_idx + 1,
                        "fields": fields,
                    })
                    logger.info(
                        "Form-field dump page %d: %d entries",
                        page_idx + 1, len(fields),
                    )
            except Exception:
                logger.exception(
                    "Form-field dump page %d failed", page_idx + 1
                )
    finally:
        try:
            doc.close()
        except Exception:
            pass

    return pages_out


def _format_form_fields_for_prompt(pages: list) -> str:
    """Render the form-field dump for embedding in the prompt."""
    if not pages:
        return "(no exhaustive form-field dump available)"
    import json as _json
    out_lines = []
    for entry in pages:
        out_lines.append(f"--- PAGE {entry['page']} ---")
        try:
            out_lines.append(
                _json.dumps(entry["fields"], ensure_ascii=False, indent=1)
            )
        except Exception:
            out_lines.append("(failed to serialize page fields)")
        out_lines.append("")
    return "\n".join(out_lines)




# ---- FORM prompt — for tax returns, applications, registration forms ----
#
# Critical differences from the certificate prompt:
#   * NO masthead rule. Forms have no institution name to put first.
#   * Mandate that EVERY visible label, code (RA1, RN3, etc.),
#     and column number appears in the output.
#   * Empty cells must still be rendered with ",00" or "—" so the
#     output has the same shape as the source.
#   * Tables are MANDATORY. A form rendered as flat paragraphs is
#     considered a complete failure.
#   * One python-docx table per logical form section (Quadro RA,
#     Quadro RN, etc.) — not a single mega-table.
_PROMPT_FORM = """\
You are translating a structured FORM (tax return, application,
registration form, etc.) and producing a Microsoft Word (.docx)
file that preserves the source's grid layout cell-by-cell.

WORKFLOW
========
You have one tool: `run_python_docx_code`. You call it with a
complete python-docx script. We run it in a sandbox and return
diagnostics. Iterate until the form fully matches the source.

REQUIREMENTS — FORM-SPECIFIC
============================
  * Translate from {source_lang} into {target_lang}.
  * Save the finished DOCX to exactly: r"{output_path}"
  * A4 page size (Cm(21) × Cm(29.7)), 1.5cm margins.
  * Body font 10pt for cells, 11pt for section headers.
  * Reproduce EVERY VISIBLE LABEL from the source. Field labels
    (e.g. "Dominical income non-revalued", "Days", "%", "Special
    cases", "Continuation"), section codes (RA1, RA2, RN1, RN3),
    and column numbers (1, 2, 3 … 16) MUST appear in your output.
  * Reproduce every value, code, and number visible in the form —
    tax codes (e.g. MSLMHL79C43H501M), monetary values (32,260),
    children's IDs, percentages (50%), date fragments.
  * Empty cells still get rendered — show ",00" for empty money
    fields, just the column number for empty number-only cells.
    The shape of the form must survive even when most cells are
    blank.
  * Use python-docx TABLES for every grid in the form. ONE
    `doc.add_table(rows=N, cols=M)` per section (Quadro RA, Quadro
    RN, etc.). Do NOT render rows as flat paragraphs — that loses
    the visual structure.
  * Borderless tables — set `tblBorders` to nil on every table.
  * Section headers ("FORM RA — Income from land", "FORM RN —
    Determination of IRPEF") get their own bold paragraph above
    each table.
  * The agency name at the top (e.g. "Revenue Agency / Agenzia
    delle Entrate"), document title ("INCOME / REDDITI"), and tax
    year ("TAX YEAR 2024 / PERIODO D'IMPOSTA 2024") should be
    typed out as the first few paragraphs in 11pt bold — NOT as
    bracketed image placeholders.
  * NEVER write [Coat of Arms], [Stamp], [Signature: ...],
    [Logo], or any other bracketed image marker.
  * NEVER write HTML tags (<p>, <br>, style="...", <center>).
    For alignment use `paragraph.alignment =
    WD_ALIGN_PARAGRAPH.CENTER`. For bold use `run.bold = True`.
  * FORBIDDEN: a CERTIFIED TRANSLATION block, "I hereby certify",
    "Translator: <email>", "Note: This is a translation of...",
    or any translator's note. The wrapper appends the real cert
    AFTER your body.

EXTRACTED IMAGES (in ./images/)
===============================
{image_list}

EXTRACTED TABLES (use these JSON values verbatim — these ARE the
form's data)
===============================
{table_list}

EXHAUSTIVE FORM-FIELD DUMP (every visible label, code, column number,
and value, page by page — use this as ground truth, do NOT skip
entries, do NOT translate the codes themselves like RA1, RN3, but
DO translate the labels into {target_lang})
===============================
{form_fields}

Begin by writing the first version of the script and calling
`run_python_docx_code`. The output must contain at least one
python-docx table per major form section.
"""


# ---- LETTER prompt — for memos, official notices, correspondence ----
_PROMPT_LETTER = """\
You are translating a LETTER or MEMO and producing a Microsoft
Word (.docx) file that preserves the source's visual layout.

WORKFLOW
========
You have one tool: `run_python_docx_code`. Call it with a
complete python-docx script. Iterate based on diagnostics.

REQUIREMENTS
============
  * Translate from {source_lang} into {target_lang}.
  * Save the finished DOCX to exactly: r"{output_path}"
  * A4 page size, 2cm margins, 11pt body.
  * Top-of-page block: sender name + sender address + date,
    aligned right. Then recipient block aligned left. Then
    subject line in bold. Then the letter body as flowing
    paragraphs. Then closing salutation. Then typed name +
    title at the bottom.
  * NO inline images. The wrapper embeds the original source
    pages BEFORE your body, so the original masthead /
    letterhead is preserved at full quality.
  * NEVER write bracketed image markers ([Coat of Arms],
    [Stamp], [Signature], etc.) or HTML tags.
  * FORBIDDEN: a CERTIFIED TRANSLATION block / "I hereby
    certify" / translator's note. The wrapper appends the
    real cert AFTER your body.

EXTRACTED IMAGES (in ./images/)
===============================
{image_list}

EXTRACTED TABLES
===============================
{table_list}

Begin by writing the first version of the script.
"""


# ---- RECEIPT prompt — for invoices, receipts, payment confirmations ----
_PROMPT_RECEIPT = """\
You are translating a RECEIPT or INVOICE and producing a Microsoft
Word (.docx) file that preserves the itemised structure.

WORKFLOW
========
One tool: `run_python_docx_code`. Iterate on diagnostics.

REQUIREMENTS
============
  * Translate from {source_lang} into {target_lang}.
  * Save the finished DOCX to: r"{output_path}"
  * A4 page size, 1.5cm margins, 11pt body, 10pt for itemised
    rows.
  * Top of page: merchant / issuer name in 14pt bold, then
    address + tax ID + receipt date in normal weight.
  * The itemised list MUST be a real python-docx table (one
    row per line item). Columns typically: description,
    quantity, unit price, total. Currency symbols and
    decimals preserved verbatim (€ 32,260,00 stays as
    "€ 32,260.00" or local convention as appropriate).
  * Totals block at the bottom: subtotal, tax, grand total,
    each on its own line, right-aligned, bold for the grand
    total.
  * NEVER write bracketed image markers or HTML tags.
  * FORBIDDEN: CERTIFIED TRANSLATION block / translator's
    note.

EXTRACTED IMAGES (in ./images/)
===============================
{image_list}

EXTRACTED TABLES
===============================
{table_list}

Begin by writing the first version of the script.
"""


def _select_prompt_for(doc_type: str) -> str:
    """Map a classifier output to a prompt template."""
    doc_type = (doc_type or "CERTIFICATE").upper().strip()
    return {
        "CERTIFICATE": _INITIAL_PROMPT,
        "FORM": _PROMPT_FORM,
        "LETTER": _PROMPT_LETTER,
        "RECEIPT": _PROMPT_RECEIPT,
        "CONTRACT": _PROMPT_LETTER,   # close enough — flowing text + clauses
        "OTHER": _INITIAL_PROMPT,     # safe default
    }.get(doc_type, _INITIAL_PROMPT)


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
  * NEVER WRITE HTML TAGS. You are authoring a python-docx
    script, NOT generating HTML. Do NOT write the literal strings
    "<p>", "<br>", "<div>", "<span>", style="...", "<b>" or any
    other HTML markup inside doc.add_paragraph(), p.add_run(),
    or any other text call. If the user asks for "centered" text,
    you set paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER (and
    `from docx.enum.text import WD_ALIGN_PARAGRAPH` at the top).
    For bold, use run.bold = True. Word renders HTML as visible
    text — the user sees the literal "<p style=...>" string in
    their document. This is a hard rule with no exceptions.
  * NEVER WRITE BRACKETED IMAGE PLACEHOLDERS as visible body
    text. Do NOT write "[Coat of Arms]", "[Stamp: ...]",
    "[Signature: ...]", "[Photo]", "[Seal]", "[Logo]", "[QR
    Code]", "[Crest]" or anything similar inside add_paragraph()
    / add_run(). Per the TEXT-ONLY rule above, omit these
    elements entirely — the source pages embedded by the wrapper
    already show the originals at full quality.
  * REQUIRED FIRST OUTPUT: the very first paragraph of your
    translation body MUST be the institution's name in
    {target_lang}, centered, BOLD, 14pt (e.g.
    "UNIVERSITY OF FLORENCE" or "MINISTRY OF THE INTERIOR").
    The second paragraph MUST be the sub-department in normal
    weight, centered (e.g. "Student Registrar's Office").
    DO NOT skip this. Even if the source PDF has the masthead
    as a graphic, type it out as text — Claude.ai chat always
    does this when given a PDF, and we want the same output.
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


def _inspect_docx(docx_bytes: bytes, doc_type: str = "CERTIFICATE") -> dict:
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

    # Filter out cert-block paragraphs before measuring "real" body
    # text — if the only content is a "CERTIFIED TRANSLATION
    # STATEMENT" / "I hereby certify" block, body chars should
    # register as ~0 so we can warn that the rebuild is empty.
    cert_block_re = re.compile(
        r"(CERTIFIED TRANSLATION|I hereby certify|Translator:|"
        r"This is a translation of)",
        re.I,
    )
    real_body_paragraphs = [
        p for p in body_paragraphs if not cert_block_re.search(p)
    ]
    body_text_chars = sum(len(p) for p in real_body_paragraphs)

    report = {
        "success": True,
        "file_size_bytes": len(docx_bytes),
        "page_count_estimate": page_count_estimate,
        "paragraph_count": len(body_paragraphs),
        "body_text_chars": body_text_chars,
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
    # Empty-body detector. If the only paragraphs we wrote are the
    # cert block (or there's almost no real text at all), Claude
    # has produced a shell document — treat this as a hard failure
    # signal so the loop retries.
    if body_text_chars < 300 and len(tables) > 0:
        warnings.append(
            "CRITICAL: your output has %d body-text chars across %d "
            "paragraphs and %d tables — but the tables are EMPTY. "
            "You generated table scaffolding without filling it with "
            "the source's labels and values. Re-emit the script and "
            "actually populate each cell using "
            "table.cell(r, c).text = ... or "
            "table.cell(r, c).paragraphs[0].add_run(...)." % (
                body_text_chars,
                len(body_paragraphs),
                len(tables),
            )
        )
    elif body_text_chars < 200:
        warnings.append(
            "CRITICAL: your output has only %d body-text chars. The "
            "source document is non-empty — you have not transcribed "
            "its content. Re-emit the script and write out the source's "
            "labels, headings, and values explicitly." % body_text_chars
        )
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

    # Detect missing masthead. If the first non-empty body
    # paragraph isn't a short centered name-like string
    # (mostly uppercase letters + spaces, <= 60 chars), warn.
    # Skip for FORM/RECEIPT — they have no institutional masthead.
    if body_paragraphs and doc_type not in ("FORM", "RECEIPT"):
        first = body_paragraphs[0].strip()
        looks_like_masthead = (
            len(first) <= 60
            and len(first) >= 4
            and re.match(r"^[A-Z][\w\s\u00C0-\u017F\-\.,'']+$", first) is not None
            and sum(c.isupper() for c in first if c.isalpha())
                >= sum(c.islower() for c in first if c.isalpha())
        )
        if not looks_like_masthead:
            warnings.append(
                f"Your output is missing the institutional masthead. "
                f"The first body paragraph is "
                f"{first[:60]!r} but should be the institution "
                f"name (e.g. 'UNIVERSITY OF FLORENCE') typed in "
                f"14pt bold, centered. Add a centered bold "
                f"masthead paragraph as the FIRST element of "
                f"your output, then the sub-department on the "
                f"next line."
            )

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

def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Count pages without holding the PDF open. Returns 1 on
    failure so callers that branch on >1 don't take the multi-page
    path against their will.
    """
    try:
        import fitz  # type: ignore
    except Exception:
        return 1
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as d:
            return max(1, len(d))
    except Exception:
        return 1


def author_rebuild_docx_multiturn(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    *,
    model: Optional[str] = None,
    max_turns: int = 6,
    timeout_per_run_seconds: int = 180,
    extra_instructions: Optional[str] = None,
) -> bytes:
    """End-to-end multi-turn Claude-authored rebuild.

    `extra_instructions`: when set, appended to the initial prompt as
    USER FEEDBACK so Claude addresses the user's concerns on this
    rebuild. Used by the Request Revision flow.

    Internally delegates to _author_rebuild_docx_multiturn_core,
    which classifies the document and routes multi-page FORMs
    through the page-by-page path.
    """
    return _author_rebuild_docx_multiturn_core(
        pdf_bytes,
        source_lang,
        target_lang,
        model=model,
        max_turns=max_turns,
        timeout_per_run_seconds=timeout_per_run_seconds,
        extra_instructions=extra_instructions,
    )


def _author_rebuild_docx_multiturn_core(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    *,
    model: Optional[str] = None,
    max_turns: int = 6,
    timeout_per_run_seconds: int = 180,
    extra_instructions: Optional[str] = None,
    _force_doc_type: Optional[str] = None,
    _disable_page_by_page: bool = False,
) -> bytes:
    """End-to-end multi-turn Claude-authored rebuild.

    `extra_instructions`: when set, appended to the initial prompt as
    USER FEEDBACK so Claude addresses the user's concerns on this
    rebuild. Used by the Request Revision flow — what the user types
    in the modal lands here verbatim so the new DOCX reflects their
    feedback (e.g. "make sure no lines are skipped", "the courses
    table needs visible borders").

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
            _strip_html_and_bracket_artifacts,
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

    # Classify the document type up front. The chosen template
    # changes the rules Claude follows so that e.g. a tax form
    # doesn't try to satisfy a "first paragraph is the institution
    # name" rule that doesn't apply to it.
    if _force_doc_type:
        doc_type = _force_doc_type.upper()
    else:
        doc_type = _classify_document(pdf_bytes)

    # Multi-page FORM documents go through the page-by-page rebuild
    # (one full multi-turn loop per page, then merge) so Claude
    # doesn't run out of output tokens mid-form.
    if (
        doc_type == "FORM"
        and not _disable_page_by_page
        and _pdf_page_count(pdf_bytes) > 1
    ):
        logger.info(
            "Routing multi-page FORM to page-by-page rebuild"
        )
        return _author_rebuild_form_page_by_page(
            pdf_bytes,
            source_lang,
            target_lang,
            model=model,
            max_turns=max_turns,
            timeout_per_run_seconds=timeout_per_run_seconds,
            extra_instructions=extra_instructions,
        )

    prompt_template = _select_prompt_for(doc_type)

    # For FORM documents do an exhaustive Vision-based field dump
    # so the authoring step has the verbatim list of every cell.
    form_fields_text = "(not applicable for this document type)"
    if doc_type == "FORM":
        try:
            form_pages = _extract_form_fields_via_vision(pdf_bytes)
            form_fields_text = _format_form_fields_for_prompt(form_pages)
            logger.info(
                "FORM field dump: %d pages extracted", len(form_pages)
            )
        except Exception:
            logger.exception("FORM field dump failed — continuing without it")

    image_list_text = (
        _vision_image_list_text
        if _vision_image_list_text
        else _format_image_list(images)
    )

    # The FORM template references {form_fields}; other templates
    # don't. Format with both kwargs — Python's str.format ignores
    # unused keys only via dict-unpacking, so build the kwargs to
    # match the active template.
    format_kwargs = dict(
        source_lang=source_lang or "the source language",
        target_lang=target_lang,
        output_path=output_path,
        image_list=image_list_text,
        table_list=_format_table_list(tables),
    )
    # Only the FORM template uses {form_fields}; only pass it if
    # the active template references it (avoid KeyError on other
    # templates that don't have the placeholder).
    if "{form_fields}" in prompt_template:
        format_kwargs["form_fields"] = form_fields_text
    initial_prompt = prompt_template.format(**format_kwargs)
    # Append user-provided revision feedback so this rebuild
    # actually addresses what the user typed in the Request
    # Revision modal. Without this, the multi-turn loop runs the
    # same prompt as before and produces effectively the same
    # output — which is why the client said "nothing changes".
    if extra_instructions and extra_instructions.strip():
        initial_prompt += (
            "\n\n"
            "USER FEEDBACK FROM PREVIOUS RUN (address these specifically)\n"
            "============================================================\n"
            "The user reviewed the previous version of this document and\n"
            "asked for the following changes. Address every point. If the\n"
            "feedback contradicts a general rule above, the user's wishes\n"
            "win for this rebuild:\n\n"
            + extra_instructions.strip()
            + "\n"
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
        # Run each tool call, append a tool_result for each.
        tool_results = []
        for tu in tool_use_blocks:
            tool_input = getattr(tu, "input", None) or {}
            tool_id = getattr(tu, "id", None)
            code = tool_input.get("code") or ""

            success, traceback_text, docx_bytes = _run_in_sandbox(
                code, output_path, timeout_seconds=timeout_per_run_seconds
            )

            if success and docx_bytes:
                inspection = _inspect_docx(docx_bytes, doc_type=doc_type)
                # Save the latest good DOCX bytes so we can return
                # them even if a later turn fails.
                last_good_docx = docx_bytes
                last_good_inspection = inspection
                report_text = (
                    "Code ran successfully.\n\n"
                    + json.dumps(inspection, ensure_ascii=False, indent=2)
                )
            else:
                report_text = (
                    "Code FAILED. Traceback:\n\n" + (traceback_text or "(no message)")
                )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": report_text,
            })

        messages.append({"role": "user", "content": tool_results})

    # Clean up extracted images dir (we keep last_good_docx in memory).
    try:
        shutil.rmtree(out_dir, ignore_errors=True)
    except Exception:
        pass

    # Final check — if the last good DOCX has near-zero body text
    # but the source PDF is non-empty, we've produced a shell
    # document. Raise rather than silently shipping empty pages.
    if last_good_docx:
        try:
            body_chars = int(
                last_good_inspection.get("body_text_chars", -1) or -1
            )
        except Exception:
            body_chars = -1
        if 0 <= body_chars < 150:
            raise RuntimeError(
                "Multi-turn rebuild produced an empty body "
                "(%d body chars across %d paragraphs). "
                "The pipeline failed to transcribe the source." % (
                    body_chars,
                    int(
                        last_good_inspection.get("paragraph_count", 0)
                        or 0
                    ),
                )
            )

    if not last_good_docx:
        raise RuntimeError(
            "Multi-turn rebuild ended with no successful DOCX produced"
        )

    logger.info(
        "Multi-turn rebuild complete: %d bytes, %d paragraphs, "
        "%d tables, %d images, page_estimate=%d",
        len(last_good_docx),
        last_good_inspection.get("paragraph_count", -1),
        last_good_inspection.get("table_count", -1),
        last_good_inspection.get("image_count", -1),
        last_good_inspection.get("page_count_estimate", -1),
    )

    # Apply the same post-processor chain as the single-shot path so
    # any residual cert blocks, table borders, rotation, broken
    # images, etc. get cleaned up deterministically.
    docx_bytes = last_good_docx
    try:
        docx_bytes = _strip_rotation_from_docx(docx_bytes)
        docx_bytes = _strip_layout_table_borders(docx_bytes)
        docx_bytes = _strip_inline_cert_blocks(docx_bytes)
        # Strip literal HTML tags and bracketed image placeholders
        # that Claude sometimes emits as visible body text (e.g.
        # "<p style=\"text-align: center;\">FOO</p>" or
        # "[Coat of Arms]"). Both should never appear in the output.
        docx_bytes = _strip_html_and_bracket_artifacts(docx_bytes)
        docx_bytes = _strip_broken_image_drawings(docx_bytes)
    except Exception:
        logger.exception("Post-processor chain raised; returning raw bytes")

    return docx_bytes


def _split_pdf_per_page(pdf_bytes: bytes) -> list:
    """Return a list of single-page PDF bytes objects, one per page
    of the input PDF. Empty list on any failure.
    """
    try:
        import io as _io
        import fitz  # type: ignore
    except Exception:
        return []
    try:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return []
    out = []
    try:
        for i in range(len(src)):
            try:
                dst = fitz.open()
                dst.insert_pdf(src, from_page=i, to_page=i)
                buf = _io.BytesIO()
                dst.save(buf)
                dst.close()
                out.append(buf.getvalue())
            except Exception:
                logger.exception("Single-page split failed on page %d", i + 1)
    finally:
        try:
            src.close()
        except Exception:
            pass
    return out


def _merge_authored_docx_fragments(fragments: list) -> bytes:
    """Concatenate multiple authored DOCX byte blobs into one. Uses
    export_wrapper._append_body_from as the body-merge primitive so
    we share its trim-trailing-blank-para / drop-sectPr handling.

    A page break is inserted between fragments so each source page
    starts on its own output page.
    """
    if not fragments:
        return b""
    if len(fragments) == 1:
        return fragments[0]
    try:
        import io as _io
        from docx import Document  # type: ignore
        from docx.enum.text import WD_BREAK  # type: ignore
        from app.services.export_wrapper import _append_body_from
    except Exception:
        logger.exception("Fragment merge unavailable — returning first only")
        return fragments[0]

    try:
        out_doc = Document(_io.BytesIO(fragments[0]))
    except Exception:
        logger.exception("Could not open fragment 0 — returning raw bytes")
        return fragments[0]

    for raw in fragments[1:]:
        # Page break between fragments.
        try:
            p = out_doc.add_paragraph()
            r = p.add_run()
            r.add_break(WD_BREAK.PAGE)
        except Exception:
            logger.exception("Page-break insertion failed")
        try:
            src_doc = Document(_io.BytesIO(raw))
            _append_body_from(src_doc, out_doc)
        except Exception:
            logger.exception("Fragment append failed")

    buf = _io.BytesIO()
    try:
        out_doc.save(buf)
        return buf.getvalue()
    except Exception:
        logger.exception("Merged DOCX save failed — returning first fragment")
        return fragments[0]


def _author_rebuild_form_page_by_page(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    *,
    model = None,
    max_turns: int = 4,
    timeout_per_run_seconds: int = 180,
    extra_instructions = None,
) -> bytes:
    """Multi-page FORM rebuild: split into single pages, run a full
    multi-turn rebuild on each, then merge the resulting DOCXs.

    Falls back to a single whole-document rebuild on any internal
    failure (so we never lose ALL pages just because one failed).

    Returns merged DOCX bytes.
    """
    pages = _split_pdf_per_page(pdf_bytes)
    if not pages or len(pages) == 1:
        logger.info(
            "Form page-by-page: %d page(s) — using whole-document path",
            len(pages),
        )
        # Fall back to whole-doc rebuild by re-entering the main
        # function with a sentinel that disables this code path
        # (avoids infinite recursion).
        return _author_rebuild_docx_multiturn_core(
            pdf_bytes,
            source_lang,
            target_lang,
            model=model,
            max_turns=max_turns,
            timeout_per_run_seconds=timeout_per_run_seconds,
            extra_instructions=extra_instructions,
            _force_doc_type="FORM",
            _disable_page_by_page=True,
        )

    fragments = []
    for i, page_pdf in enumerate(pages, start=1):
        logger.info(
            "Form page-by-page: rebuilding page %d / %d",
            i, len(pages),
        )
        try:
            page_extra = (
                (extra_instructions or "")
                + f"\n\nThis is PAGE {i} of {len(pages)} of a multi-page "
                "form. Translate this page only. Do not add masthead or "
                "cert blocks — the wrapper handles those."
            ).strip()
            page_docx = _author_rebuild_docx_multiturn_core(
                page_pdf,
                source_lang,
                target_lang,
                model=model,
                max_turns=max_turns,
                timeout_per_run_seconds=timeout_per_run_seconds,
                extra_instructions=page_extra,
                _force_doc_type="FORM",
                _disable_page_by_page=True,
            )
            fragments.append(page_docx)
        except Exception:
            logger.exception(
                "Form page %d rebuild failed — skipping page", i
            )

    if not fragments:
        raise RuntimeError(
            "Form page-by-page rebuild produced no successful pages"
        )

    merged = _merge_authored_docx_fragments(fragments)
    logger.info(
        "Form page-by-page complete: merged %d fragment(s) -> %d bytes",
        len(fragments), len(merged),
    )
    return merged

