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

# ---- UNIVERSAL prompt — Claude.ai-parity approach -------------
#
# Every prior version of this prompt accumulated rules patching
# specific failure modes. Each rule removed a degree of freedom
# Claude needs to handle documents we haven't seen. Stripping
# down to the essentials — trusting Claude's judgment for layout
# while keeping the post-processors as the safety net — matches
# how Claude.ai chat handles arbitrary document uploads.
#
# The classifier still runs (cheap Haiku Vision call) and the
# result becomes a 2-3 line HINT inside the universal prompt
# rather than picking from a fork of 4 different templates.

_UNIVERSAL_PROMPT = """\
You are translating a document and producing a Microsoft Word
(.docx) file that closely matches the source's visual layout.

Tool: `run_python_docx_code`. Write a complete python-docx Python
script, we run it in a sandbox, you see diagnostics
(file size, page count, paragraph samples, image / table counts,
body-text char count, warnings), then iterate until the output
matches the source.

Save the final DOCX to exactly: r"{output_path}"

Translate from {source_lang} into {target_lang}.

Match the source's structure faithfully. Use python-docx tables
for tabular data, paragraphs for flowing text, headings where
the source has them. Preserve colors, column widths, and section
styles when they're visually meaningful. Use python-docx native
styling — paragraph.alignment, run.bold, run.underline,
run.font.color.rgb, and the _shade(cell, hex) helper for cell
backgrounds. NEVER write HTML tags as visible text.

CONSOLIDATE TABLES. One python-docx table per LOGICAL SECTION.
If the source has 29 rows under a single heading, that's ONE
table with 29 rows — NOT 29 one-row tables. Creating a separate
table per row is the most common failure mode of this pipeline;
don't do it.

MERGE CELLS for headers. When a section title spans the full
width of a table (e.g. "SECTION RN — Determination of IRPEF"),
use _merge_row(table, 0, "...", bold=True) so the title appears
ONCE in a merged cell — don't duplicate the same text across
every column. Same for column groupings: use _merge_col() for
vertical spans.

ONE TABLE, MANY ROWS — example pattern:

    section_table = doc.add_table(rows=1 + len(rows_data), cols=N)
    _merge_row(section_table, 0, "SECTION RN — IRPEF", bold=True)
    for i, (code, label, val) in enumerate(rows_data, start=1):
        _set_cell(section_table, i, 0, code, bold=True)
        _set_cell(section_table, i, 1, label)
        _set_cell(section_table, i, 2, val, align="right")

HARD RULES (these prevent known failure modes — every other
decision is your judgment call):

  * No CERTIFIED TRANSLATION / "I hereby certify" / translator's
    note block ANYWHERE in your output. The wrapper appends the
    real cert AFTER your body.
  * No HTML tags as visible text. If you want centered text use
    `paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER`, never
    write `<center>` / `<p style="...">` / `<br>`.
  * No bracketed image placeholders like [Coat of Arms],
    [Stamp: ...], [Signature: ...], [Photo], [Logo].
    Type out names; the wrapper embeds original source pages
    as the visual reference for stamps/signatures.
  * Do NOT call doc.add_picture(...) anywhere in your script.
    The wrapper provides the original source pages BEFORE your
    body, so coat of arms / logos / stamps / signatures are
    already shown in their proper form. Inserting images from
    ./images/ here usually produces a desk-background or
    paper-edge crop where the official symbol should be.
  * A4 page size unless the source is obviously different.

Helper recipes you can paste at the top of your script:

    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    def _shade(cell, hex_color):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color)
        tcPr.append(shd)

    def _text_color(run, hex_color):
        r, g, b = (
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16),
        )
        run.font.color.rgb = RGBColor(r, g, b)

    def _merge_row(table, row_idx, text=None, *, bold=False, align="center"):
        # Merge every cell in row `row_idx` into one wide cell.
        # If `text` is given, write it once into the merged cell.
        # Use this for section-header rows that span the full table
        # width. DO NOT duplicate the same text across every column.
        cells = table.rows[row_idx].cells
        merged = cells[0].merge(cells[-1])
        if text is not None:
            merged.text = ""
            p = merged.paragraphs[0]
            if align == "center":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif align == "right":
                from docx.enum.text import WD_ALIGN_PARAGRAPH as _A
                p.alignment = _A.RIGHT
            run = p.add_run(text)
            run.bold = bold
        return merged

    def _merge_col(table, col_idx, row_start, row_end):
        # Merge a vertical run of cells in one column.
        # Use for column headers that span multiple header rows.
        top = table.cell(row_start, col_idx)
        bot = table.cell(row_end, col_idx)
        return top.merge(bot)

    def _set_cell(table, row, col, text, *, bold=False, align=None):
        # Replace a cell's content cleanly. Clears existing
        # paragraphs first so you don't double-up text.
        cell = table.cell(row, col)
        cell.text = ""
        p = cell.paragraphs[0]
        if align == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "right":
            from docx.enum.text import WD_ALIGN_PARAGRAPH as _A
            p.alignment = _A.RIGHT
        run = p.add_run(text)
        run.bold = bold

DOCUMENT-TYPE HINT
==================
This document looks like a {doc_type_label}.
{type_hint}

EXTRACTED IMAGES (in ./images/, if any)
=======================================
{image_list}

EXTRACTED TABLES (use these JSON values verbatim if present)
=======================================
{table_list}

{form_fields_section}

Begin by writing the first version of your script and calling
`run_python_docx_code`. Use your judgment for everything not
covered by the hard rules.
"""


# Tiny, focused hints per document type. Replace 100+ lines of
# per-type rules with 2-4 lines that orient Claude's judgment.
_TYPE_HINTS = {
    "CERTIFICATE": (
        "  * Institution name as a centered bold heading near the top "
        "(typed out, not as an image).\n"
        "  * Match the source's centered-title + bold-subheading +\n"
        "    underlined-fill-in-value pattern where present.\n"
        "  * Keep stamps and signatures as text (officer name + title) "
        "only; the wrapper provides the originals on separate pages."
    ),
    "FORM": (
        "  * ONE python-docx table per logical section. RN1..RN31 "
        "belong in the SAME table as separate rows. NEVER create "
        "one-row tables per RN/RA entry.\n"
        "  * For section-header rows that span the full width, call "
        "_merge_row(table, 0, 'SECTION NAME', bold=True). Do NOT "
        "write the section name into every column cell.\n"
        "  * STRICT column widths. For each table whose section "
        "has col_widths in SECTION STYLES, set table.autofit=False "
        "AND apply the proportions verbatim:\n"
        "      page_cm = 18.0  # A4 portrait usable width\n"
        "      table.autofit = False\n"
        "      for i, w in enumerate(col_widths):\n"
        "          table.columns[i].width = Cm(page_cm * w / 100)\n"
        "    For tables with >10 columns the wrapper switches the\n"
        "    page to landscape automatically; size for 26cm width\n"
        "    when col_widths sum to 100 and the table is wide.\n"
        "  * RN SUB-FIELDS as a NESTED TABLE inside the sub-detail "
        "cell. When an RN entry has N sub-fields (e.g. RN6 has "
        "Spouse / Children / Other) render them SIDE-BY-SIDE using "
        "a 1xN nested table inside the cell, NOT stacked paragraphs:\n"
        "      sub_cell = rn_table.cell(i, 2)\n"
        "      sub_cell.text = \"\"\n"
        "      inner = sub_cell.add_table(rows=2, cols=len(subs))\n"
        "      for j, (lbl, val) in enumerate(subs):\n"
        "          _set_cell(inner, 0, j, lbl, size_pt=7)\n"
        "          _set_cell(inner, 1, j, val, size_pt=8, bold=bool(val))\n"
        "    This matches the source layout where columns 1-3 of "
        "an RN row sit horizontally, not vertically.\n"
        "  * Empty cells render as ',00' or just the column number "
        "to preserve the form's grid shape.\n"
        "  * Use EXTRACTED TABLES + EXHAUSTIVE FIELD DUMP as ground "
        "truth. Apply SECTION STYLES header_fill / body_fill via "
        "_shade(cell, hex)."
    ),

    "LETTER": (
        "  * Top: sender address + date on the right, then recipient "
        "left, then bold subject line.\n"
        "  * Body as flowing paragraphs.\n"
        "  * Bottom: closing salutation + typed name + title."
    ),
    "RECEIPT": (
        "  * Merchant / issuer name in 14pt bold at the top.\n"
        "  * Itemised list as a python-docx table (description, qty, "
        "unit price, total).\n"
        "  * Totals block right-aligned at the bottom, grand total bold."
    ),
    "CONTRACT": (
        "  * Title centered + bold at the top.\n"
        "  * Numbered clauses as separate paragraphs preserving the "
        "source's numbering scheme.\n"
        "  * Signature lines at the bottom."
    ),
    "OTHER": (
        "  * Match the source's general structure — headings, "
        "paragraphs, tables, images where they appear."
    ),
}


def _type_label(doc_type: str) -> str:
    """Human-readable form of a classifier output."""
    return {
        "CERTIFICATE": "official certificate or transcript",
        "FORM": "structured form (tax return, application, registration)",
        "LETTER": "letter or memo",
        "RECEIPT": "receipt or invoice",
        "CONTRACT": "contract or agreement",
        "OTHER": "general document",
    }.get(doc_type.upper(), "general document")


def _select_prompt_for(doc_type: str) -> str:
    """Return the universal prompt — type-specific rules now live
    in {type_hint} placeholder inside the template.
    """
    return _UNIVERSAL_PROMPT


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



# Models that have ADAPTIVE thinking always-on at the API level:
# they reject (or warn on) the explicit `thinking` parameter that
# extended-thinking-capable models use. Fable 5 and Mythos 5 fall
# in this category per the Anthropic docs (June 2026 launch).
_ADAPTIVE_THINKING_MODELS = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-mythos-preview",
)


def _uses_adaptive_thinking(model: str) -> bool:
    """True for models where we must skip the explicit thinking arg."""
    m = (model or "").strip().lower()
    return any(m.startswith(prefix) for prefix in _ADAPTIVE_THINKING_MODELS)


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
    "application, registration form, or similar).\n\n"
    "PART A — Field listing.\n"
    "List every visible label, section code (RA1, RN3, etc.), column "
    "number (1..16), filled-in value (tax code, amount, percentage, "
    "date, ID), and section title.\n\n"
    "PART B — Style metadata.\n"
    "Identify the visual style of each form section: header bar fill "
    "color, body background fill color, text color, and how many "
    "columns the section's data grid uses with their approximate width "
    "proportion (sums to 100).\n\n"
    "Output ONE JSON OBJECT with two top-level keys:\n"
    "  'fields' : ARRAY of field entries, each an object with keys:\n"
    "    - 'kind'  : one of section_title, field_label, section_code, "
    "column_number, value, checkbox, instruction_note\n"
    "    - 'text'  : verbatim source-language text\n"
    "    - 'group' : the section this belongs to (e.g. 'QUADRO RA', "
    "'QUADRO RN', 'Header')\n"
    "  'sections' : ARRAY of section style entries, one per logical "
    "section, each an object with keys:\n"
    "    - 'name'         : section identifier matching the 'group' "
    "values used above\n"
    "    - 'header_fill'  : hex color of the section header bar "
    "(e.g. '1F4E79') or null if no shaded header\n"
    "    - 'body_fill'    : hex color of the cell background or "
    "null for plain white\n"
    "    - 'text_color'   : hex color of the label text (e.g. "
    "'FFFFFF' for white-on-blue) or null for default black\n"
    "    - 'columns'      : integer column count for this section's "
    "main grid (or null if no grid)\n"
    "    - 'col_widths'   : array of integers summing to 100, each "
    "the percent width of one column from left to right (or null "
    "if 'columns' is null)\n\n"
    "Be exhaustive. Empty value cells still get a field entry with "
    "text ',00' or '\u2014'. Reply with ONLY the JSON object, no "
    "prose, no code fence."
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
                parsed = None
                try:
                    parsed = _json.loads(raw)
                except Exception:
                    # Try object {} first, then array [] as legacy
                    # fallback.
                    for op, cl in (("{", "}"), ("[", "]")):
                        start = raw.find(op)
                        end = raw.rfind(cl)
                        if start != -1 and end != -1 and end > start:
                            try:
                                parsed = _json.loads(raw[start:end + 1])
                                break
                            except Exception:
                                continue
                fields = []
                sections = []
                if isinstance(parsed, dict):
                    fields = parsed.get("fields") or []
                    sections = parsed.get("sections") or []
                elif isinstance(parsed, list):
                    # Legacy array-only shape.
                    fields = parsed
                if fields or sections:
                    pages_out.append({
                        "page": page_idx + 1,
                        "fields": fields,
                        "sections": sections,
                    })
                    logger.info(
                        "Form-field dump page %d: %d fields, %d "
                        "styled sections",
                        page_idx + 1, len(fields), len(sections),
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
    """Render the form-field dump (incl. per-section style metadata)
    for embedding in the prompt.
    """
    if not pages:
        return "(no exhaustive form-field dump available)"
    import json as _json
    out_lines = []
    for entry in pages:
        out_lines.append(f"--- PAGE {entry['page']} ---")
        try:
            out_lines.append("FIELDS:")
            out_lines.append(
                _json.dumps(
                    entry.get("fields", []),
                    ensure_ascii=False,
                    indent=1,
                )
            )
        except Exception:
            out_lines.append("(failed to serialize page fields)")
        sections = entry.get("sections") or []
        if sections:
            try:
                out_lines.append("SECTION STYLES:")
                out_lines.append(
                    _json.dumps(sections, ensure_ascii=False, indent=1)
                )
            except Exception:
                pass
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
_PROMPT_FORM = _UNIVERSAL_PROMPT  # aliased to universal prompt


# ---- LETTER prompt — for memos, official notices, correspondence ----
_PROMPT_LETTER = _UNIVERSAL_PROMPT  # aliased to universal prompt


# ---- RECEIPT prompt — for invoices, receipts, payment confirmations ----
_PROMPT_RECEIPT = _UNIVERSAL_PROMPT  # aliased to universal prompt


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


_INITIAL_PROMPT = _UNIVERSAL_PROMPT  # aliased to universal prompt


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
    max_turns: int = 10,
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
    max_turns: int = 10,
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
            _merge_adjacent_compatible_tables,
            _auto_landscape_wide_tables,
            _collapse_pre_section_whitespace,
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

    # Universal prompt receives all kwargs every time. {form_fields_section}
    # is set to either the JSON dump block (FORM) or a small "(not
    # applicable)" note.
    if doc_type == "FORM" and form_fields_text and form_fields_text != "(not applicable for this document type)":
        form_fields_section = (
            "EXHAUSTIVE FORM-FIELD DUMP (every visible label / code / "
            "column number / value per page — use as ground truth)\n"
            "===================================================\n"
            + form_fields_text
        )
    else:
        form_fields_section = ""

    format_kwargs = dict(
        source_lang=source_lang or "the source language",
        target_lang=target_lang,
        output_path=output_path,
        image_list=image_list_text,
        table_list=_format_table_list(tables),
        doc_type_label=_type_label(doc_type),
        type_hint=_TYPE_HINTS.get(
            doc_type.upper(), _TYPE_HINTS["OTHER"]
        ),
        form_fields_section=form_fields_section,
    )
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

    chosen_model = (
        model
        or os.getenv("REBUILD_DEFAULT_MODEL")
        or "claude-fable-5"
    )
    last_good_docx: bytes = b""
    last_good_inspection: dict = {}

    for turn in range(1, max_turns + 1):
        logger.info(
            "Multi-turn rebuild: turn %d/%d (model=%s)",
            turn, max_turns, chosen_model,
        )
        try:
            # Build the API call. Extended thinking + larger token
            # budget = closer to Claude.ai chat behavior. Thinking
            # is optional (fails gracefully on older SDKs).
            api_kwargs = dict(
                model=chosen_model,
                max_tokens=32000,
                tools=[_TOOL_DEFINITION],
                messages=messages,
            )
            # Skip explicit thinking for models that already do
            # adaptive thinking always-on (Fable 5, Mythos 5).
            allow_thinking = (
                os.getenv("REBUILD_EXTENDED_THINKING", "1").lower()
                not in ("0", "false", "no", "off")
                and not _uses_adaptive_thinking(chosen_model)
            )
            if allow_thinking:
                # 12000 thinking tokens — enough to plan a long
                # document. The Anthropic SDK accepts a "thinking"
                # parameter on models that support it; we wrap in
                # try/except below to handle SDKs that don't.
                api_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": 12000,
                }
            try:
                resp = client.messages.create(**api_kwargs)
            except TypeError:
                # SDK didn't accept "thinking" — retry without it.
                api_kwargs.pop("thinking", None)
                resp = client.messages.create(**api_kwargs)
            except Exception as _e:
                msg = str(_e)
                # Some models reject thinking + tools; retry plain.
                if "thinking" in msg.lower() and "thinking" in api_kwargs:
                    api_kwargs.pop("thinking", None)
                    resp = client.messages.create(**api_kwargs)
                else:
                    raise
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
        # Merge adjacent 1-row tables that have the same column
        # structure into a single multi-row table. Catches the
        # "29 one-row tables for RN1..RN29" fragmentation that
        # Claude still produces sometimes.
        docx_bytes = _merge_adjacent_compatible_tables(docx_bytes)
        # Wide tables get switched to landscape A4 sections so
        # they don't overflow portrait page width.
        docx_bytes = _auto_landscape_wide_tables(docx_bytes)
        # Strip empty paragraphs between page breaks and next section.
        docx_bytes = _collapse_pre_section_whitespace(docx_bytes)
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

