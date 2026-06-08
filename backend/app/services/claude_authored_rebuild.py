"""Claude-authored DOCX rebuild.

This service is the "Premium rebuild" path: instead of OCR →
per-segment translate → template-driven assembly, we hand the entire
source PDF to Claude Sonnet and ask Claude to author a complete
python-docx script that translates the document AND faithfully
reproduces its layout (tables, columns, alignment, images, stamps).

We then execute that script inside a subprocess sandbox with a tight
timeout and a restricted PYTHONPATH so only python-docx is reachable.
The script writes the finished DOCX to a known temp path; we read it
back and return the bytes.

This is intentionally slow and expensive — quality first. Each run
typically takes 60-180 seconds and consumes ~30-80k tokens.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# The author prompt. Two design notes:
#
#   1. We ask Claude for a *complete, runnable* python-docx script.
#      Claude.ai already excels at this when users paste a PDF — we
#      simulate that workflow exactly by sending the PDF as a
#      `document` content block and asking for code.
#
#   2. We enforce the output path so the sandbox knows where to read
#      the result back from. The model is told this is the *only*
#      file system path it may write to.
# ----------------------------------------------------------------
_AUTHOR_PROMPT_TEMPLATE = textwrap.dedent("""
TASK
====
Translate the attached document from {source_lang} into {target_lang}
and deliver it as a Microsoft Word (.docx) file that preserves the
original layout as faithfully as possible. The result should read as
a clean, professional translation.

OUTPUT FORMAT
=============
Return ONE Python 3 code block (```python … ```). No prose, no
preamble, no commentary. The script must:

  * Use only `python-docx` and the Python stdlib.
  * Build the document in memory and save to this exact path:
        OUTPUT_PATH = r"{output_path}"
        doc.save(OUTPUT_PATH)
  * Not touch any other file. Not call subprocess, os.system,
    requests, urllib, socket, or any network module. Not print.

OUTPUT REQUIREMENTS
===================
  * .docx format, A4 page size (21cm × 29.7cm). Do NOT use US
    Letter unless the source is clearly Letter-sized (8.5×11 in).
    Set explicitly:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

  * PAGE-FOR-PAGE FIDELITY (this is the most important rule):
    If the source PDF has N pages, the output MUST have EXACTLY N
    pages. One source page = one output page. Period.
    To guarantee this:
      - Use body font size 8pt or 9pt (never larger than 10pt).
      - Use line spacing 1.0 (single) — never 1.15 or 1.5.
      - Use paragraph_format.space_after = Pt(2) for every body
        paragraph. Default Word spacing (~10pt) wastes vertical room.
      - Use paragraph_format.space_before = Pt(0).
      - For data tables: 7pt or 8pt font in cells, single line
        spacing, minimal cell padding.
      - If a single source page is still threatening to overflow at
        7pt body / 7pt table font, drop the body to 6.5pt and
        tighten cell padding further (set
        cell._tc.get_or_add_tcPr() and zero out tcMar).
      - End every page with explicit
        run.add_break(WD_BREAK.PAGE) at the position that matches
        the source's page break. Do NOT rely on Word's natural
        pagination to "probably" land on the right page.

    Count the source pages BEFORE writing the script. After writing,
    mentally walk through: "page 1 of source → these elements of my
    script → page break → page 2 of source → these elements → page
    break → ..." If the math doesn't add up, shrink fonts more.
  * Use a serif body font (Times New Roman / Liberation Serif /
    Cambria) if the source is a formal document (certificate,
    diploma, legal/administrative paper). Use a sans-serif body
    font (Calibri / Arial) if the source itself uses one (modern
    business letter, receipt, etc.).
  * Body text 10-11pt. Drop to 8-9pt for dense tables. Headings
    follow the original's relative sizing (the title is biggest,
    section headers next).
  * If the source has a recurring header/footer (institution name,
    page number, certificate number), use Word's section header /
    footer so it auto-repeats on every page.

DOCUMENT TYPE ADAPTATION
========================
First, look at the source PDF and identify its document type. The
choice of layout structure depends on it. Common types and the
pattern that fits each:

  * CERTIFICATE / DIPLOMA / TRANSCRIPT / OFFICIAL ATTESTATION
    Repeating institutional masthead, formal body paragraphs, often
    a data table (courses/grades, exam results), signature + seal
    block at the bottom of the last page, decoding keys, italic
    translator's note. → use the PROVEN RECIPE below verbatim
    (substitute the actual institution name, IDs, dates, course
    titles, S.S.D. codes etc.).

  * BUSINESS / OFFICIAL LETTER
    Letterhead at the top (logo + sender details, sometimes only
    on page 1), date right-aligned, recipient block left-aligned,
    salutation, body paragraphs, sign-off ("Sincerely,"), signature
    image + typed name. NO repeating masthead — just page 1 has
    the letterhead. Body paragraphs are left-aligned or justified.
    No data table unless one is explicit in the source.

  * CONTRACT / AGREEMENT
    No letterhead. Centered title at the top of page 1. Numbered
    or lettered sections ("1. DEFINITIONS", "2. SCOPE", …). Each
    section has bold heading + justified body paragraphs.
    Signature block at the very end with two side-by-side panels:
    "PARTY A" + name + signature image vs "PARTY B" + name +
    signature image, both with date lines.

  * INVOICE / RECEIPT / QUOTE
    Header block: company info (left) and the word "INVOICE" plus
    invoice number, date, due date (right) — borderless 2-col
    table. Customer info paragraph. Then a bordered table of line
    items with columns "Description | Qty | Unit Price | Amount".
    Totals block right-aligned at the bottom: subtotal, tax,
    total. Payment terms paragraph. Often a footer note.

  * ID CARD / PASSPORT / DRIVER'S LICENSE
    Compact fielded layout. Photo on one side, fields on the other:
    "Name", "Date of birth", "Place of birth", "Issued", "Expires",
    "Card no.". Use a borderless table with field labels in column
    0 (bold) and values in column 1. Keep it tight — 1 page max.

  * MEDICAL REPORT / LAB RESULT / MEDICAL RECORD
    Hospital/lab letterhead, patient info block, ordering physician
    info, then either a results table (test | value | range | flag)
    or narrative paragraphs ("Findings:", "Impression:"). Signature
    of the reporting physician at the bottom.

  * MARKETING / BROCHURE / CONTENT PAGE
    Free-form layout. Centered or left-aligned title, body
    paragraphs, possibly callout boxes (use a single-row borderless
    table with a light shade fill for the callout). No formal
    masthead pattern.

  * ACADEMIC PAPER / RESEARCH ARTICLE
    Title (centered, bold). Authors (centered, italic). Abstract
    (justified, slightly indented). Numbered sections with bold
    headings. Body justified. Reference list at the end with
    hanging-indent paragraphs.

For document types not listed: pick the closest match and adapt.
The HARD RULES (no rotation, borderless layout tables, ALL data
distributed cell-by-cell in data tables, real images via
doc.add_picture) apply to ALL document types.

PROVEN PYTHON-DOCX RECIPE (certificate / diploma type)
=======================================================
For a formal certificate / diploma / official document that has a
repeating masthead on every page, use Word's section header so the
masthead auto-repeats. Here is the EXACT structure that produced
the gold-standard output on a Florence university certificate — use
it as a template for the CERTIFICATE document type. Other types
should adapt the relevant pieces (drop the section.header masthead
for letters/contracts, change the data table columns for invoices/
medical reports, etc.).

```python
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.shared import Cm, Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

def _no_borders(tbl):
    tblPr = tbl._tbl.find(qn('w:tblPr'))
    if tblPr is None:
        tblPr = OxmlElement('w:tblPr')
        tbl._tbl.insert(0, tblPr)
    borders = OxmlElement('w:tblBorders')
    for edge in ("top","left","bottom","right","insideH","insideV"):
        e = OxmlElement(f'w:{{edge}}')
        e.set(qn('w:val'), 'nil')
        borders.append(e)
    tblPr.append(borders)

doc = Document()
section = doc.sections[0]
# Extra top margin to make room for the section header masthead.
section.top_margin = Cm(4)
section.bottom_margin = Cm(2)
section.left_margin = Cm(2)
section.right_margin = Cm(2)

# === SECTION HEADER (auto-repeats on every page) ===
hdr = section.header
# Clear default empty paragraph
for p in list(hdr.paragraphs):
    p._element.getparent().remove(p._element)

# 1. Borderless 2-col table: logo | institution name stacked
t = hdr.add_table(rows=1, cols=2))
_no_borders(t)
t.columns[0].width = Cm(4)
t.columns[1].width = Cm(13)

logo_cell = t.rows[0].cells[0]
logo_cell.paragraphs[0].add_run().add_picture(
    "images/p1_header.png", width=Cm(3)
)

name_cell = t.rows[0].cells[1]
name_p = name_cell.paragraphs[0]
# Stack institution name as separate runs with line breaks INSIDE
# one paragraph. Then add italic gloss inline on the last line.
r1 = name_p.add_run("UNIVERSITÀ"); r1.bold = True; r1.font.size = Pt(12)
r1.add_break()
r2 = name_p.add_run("DEGLI STUDI"); r2.bold = True; r2.font.size = Pt(12)
r2.add_break()
r3 = name_p.add_run("FIRENZE"); r3.bold = True; r3.font.size = Pt(12)
gloss = name_p.add_run("   (University of Florence)")
gloss.italic = True; gloss.font.size = Pt(9)

# 2. Centered office name
p = hdr.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Student Registrar's Office"); r.bold = True

# 3. Cert No. (left) — Student ID No. (right), via right-aligned tab
p = hdr.add_paragraph()
pf = p.paragraph_format
pf.tab_stops.add_tab_stop(Cm(17), WD_TAB_ALIGNMENT.RIGHT)
p.add_run("Certificate No. 20251529859 /M1297_MC")
p.add_run("\t")
p.add_run("Student ID No. 7043077")

# 4. For Foreign Use (left) — Page N of M (right)
p = hdr.add_paragraph()
pf = p.paragraph_format
pf.tab_stops.add_tab_stop(Cm(17), WD_TAB_ALIGNMENT.RIGHT)
p.add_run("For Foreign Use")
p.add_run("\t")
p.add_run("Page 1 of 2")

# === BODY ===
# Centered subtitle, then justified body paragraphs.
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("HAVING EXAMINED THE OFFICIAL RECORDS, IT IS CERTIFIED, AT THE REQUEST OF THE INTERESTED PARTY, THAT")
r.bold = True

p = doc.add_paragraph("Dr. BALICE RAFFAELE, born on 02/06/1985 in Milan (MI), of ITALIAN citizenship, passed at this University the final examination of the Second-Level Master's Degree in LEADERSHIP AND STRATEGIC ANALYSIS on 17/02/2020 with a grade of 103/110.")
p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

doc.add_paragraph("It is further certified that the interested party submitted the following Statutory study plan:").alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

p = doc.add_paragraph(); r = p.add_run("FIRST YEAR"); r.bold = True

# Courses table — 8 columns. CHECK THE SOURCE: if the source
# uses whitespace alignment (no visible borders between cells),
# make this table borderless too. Florence-style certificates
# are borderless — call _no_borders(table) right after add_table.
table = doc.add_table(rows=1, cols=8)
_no_borders(table)  # remove this line ONLY if source has visible borders
header_cells = table.rows[0].cells
for i, label in enumerate(["Course Code", "Course", "Outcome", "Grade", "CFU", "S.S.D.", "Date", "Teaching Course (*)"]):
    p = header_cells[i].paragraphs[0]
    r = p.add_run(label); r.bold = True; r.font.size = Pt(9)

# Add each course on its own row. CRITICAL: distribute values
# one-per-cell. Never put a whole row into cell 0.
rows = [
    ("30610002", "ADMINISTRATIVE LAW", "Passed", "29/30", "6", "IUS/10", "28/11/2019", "10 3061 PDS0-2019"),
    # ... etc, one tuple per course
]
for row in rows:
    cells = table.add_row().cells
    for i, val in enumerate(row):
        cells[i].text = val
        for p in cells[i].paragraphs:
            for r in p.runs:
                r.font.size = Pt(8)

# === SIGNATURE BLOCK ===
# Borderless 2-col table: officer name + signature image on left,
# round seal on right.
sig = doc.add_table(rows=1, cols=2))
_no_borders(sig)
left = sig.rows[0].cells[0]
left.paragraphs[0].add_run("The Issuing Officer\nBETTI ILARIA").bold = True
left.add_paragraph().add_run().add_picture("images/p2_signature.png", width=Cm(5))
right = sig.rows[0].cells[1]
right.paragraphs[0].add_run().add_picture("images/p2_seal.png", width=Cm(3))

# === DECODING SECTION + TRANSLATOR'S NOTE ===
doc.add_paragraph("(*) Decoding of the institution-triad codes appearing in the document:")
# ... etc, then a small 3-row x 2-col borderless table for S.S.D. codes
# NO translator's note paragraph. Stop after the last translated
# content. The wrapper appends the official certification page
# after your output.



# IMPORTANT: python-docx's Document.add_table() does NOT accept a
# "width" keyword argument. To control table / column widths, set
# them AFTER creating the table:
#
#   t = doc.add_table(rows=1, cols=2)
#   t.autofit = False
#   t.allow_autofit = False
#   t.columns[0].width = Cm(4)
#   t.columns[1].width = Cm(13)
#   for row in t.rows:
#       row.cells[0].width = Cm(4)
#       row.cells[1].width = Cm(13)
#
# Use this pattern for EVERY table in the script. Never pass width=
# to add_table() — it will TypeError.

doc.save(OUTPUT_PATH)
```

USE this exact structure as your template. Substitute the
language / strings / dates for the actual source document. For
non-certificate documents (business letter, contract, etc.) keep
the same skeleton but drop sections that don't apply (e.g. omit
the Cert No tab-stop row if the source doesn't have one).

LAYOUT TO REPRODUCE
===================
Read the document end-to-end and reproduce its visual structure:

  * Masthead / letterhead: extract from page 1 and replicate at
    the top of the output. If the source shows a logo on the LEFT
    and an institution name STACKED next to it, use a borderless
    2-column layout (column 1 = logo, column 2 = stacked name).
    Never stack the name UNDER the logo unless the source does.
  * If a document name (institution, organisation, hospital, court,
    company) is iconic and identifying — leave it in the original
    language and add a small italic gloss in {target_lang} on the
    same line. E.g. "UNIVERSITÀ DEGLI STUDI FIRENZE (University of
    Florence)".
  * Two-label rows (e.g. "Certificate No. X  •  Student No. Y", or
    "Date: …  •  Reference: …" sitting on the same line in the
    source) → single paragraph with tab stops, NOT two paragraphs,
    NOT a 2-cell table.
  * Centered titles centered, justified body paragraphs justified,
    right-aligned numbers right-aligned. Match the source exactly.
  * Border style on the data grid table MUST match the source.
    Look at the source PDF: does the courses-and-grades grid (or
    invoice line items table, or whatever the main data table is)
    have visible borders between cells, or does it use whitespace
    alignment only?
      - source uses pure whitespace alignment → make the data table
        BORDERLESS too (call _no_borders(table) just like for
        layout tables).
      - source uses light/thin grey lines → use Table Grid then
        override to 0.5pt grey borders.
      - source uses heavy black borders → use Table Grid as-is.
    For the Florence-style university certificate where the courses
    list is just whitespace-aligned columns with no visible cell
    boundaries, the output data table MUST be borderless.
  * Layout tables (logo|name header, label|value rows, signature
    blocks, decoding key tables) are ALWAYS borderless regardless
    of the source. Use this helper for them:

        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        def _no_borders(tbl):
            tblPr = tbl._tbl.find(qn('w:tblPr'))
            if tblPr is None:
                tblPr = OxmlElement('w:tblPr')
                tbl._tbl.insert(0, tblPr)
            borders = OxmlElement('w:tblBorders')
            for edge in ("top","left","bottom","right","insideH","insideV"):
                e = OxmlElement(f'w:{{edge}}')
                e.set(qn('w:val'), 'nil')
                borders.append(e)
            tblPr.append(borders)

  * Signature blocks (officer name + signature image + seal/stamp
    image) sit at the bottom of the issuing page in a borderless
    2- or 3-column layout. Reproduce the same layout.
  * Decoding keys / legends / footnotes at the very end of the
    source appear at the end of the output in the same compact
    layout (small font, indented).
  * If a column needs wider space than the page allows, drop the
    font to 7-8pt — never rotate the text, never switch to
    landscape mid-document.

TRANSLATION PRINCIPLES
======================
Translate all descriptive prose, headings, course titles, paragraph
body, and table labels. Translate naturally — register matches the
source (formal, legal, conversational, marketing, etc.).

Preserve verbatim (do NOT translate or alter):
  * Personal names, place names, institution names (translate the
    type word — "Università" → "University" — only when the name
    is descriptive, not iconic).
  * All identifiers: certificate numbers, student / customer /
    invoice IDs, file references, internal codes (e.g. "PDS0-2019",
    "10 3061").
  * All scientific / disciplinary / industry codes (IUS/10,
    SPS/04, ISO codes, CPT codes, ICD codes, NACE codes, etc.).
  * Numeric values: credit counts, grades ("29/30", "103/110"),
    monetary amounts, dates (keep the source's date format —
    DD/MM/YYYY stays DD/MM/YYYY).
  * Legal references and decree numbers ("D.P.R. 26/10/1972 no.
    642" → "Presidential Decree No. 642 of 26/10/1972" — translate
    the type, keep article + date + number intact).
  * Exam/state outcomes that are normally translated 1:1
    ("Superato"/"Passed", "Approvato"/"Approved", "Reso"/"Returned",
    etc.).

When in doubt, prefer "leave the original + add gloss in target
language in italics" over "drop the original altogether".

ARTWORK / IMAGES — DO NOT EMBED ANY
====================================
The user has explicitly instructed: NO inline images anywhere
in the translation body. Do NOT call doc.add_picture() at all,
regardless of whether image files exist in ./images/. Do NOT
insert any bracketed image placeholder like "[Coat of Arms]"
or "[Signature]" either.

Why: the export wrapper embeds the FULL source PDF pages
BEFORE your translation body, so the original crest, signature,
seal, stamp, photo, QR code, and every other graphic element
is already preserved in the export at full visual fidelity.
Re-rendering them inline produces blurry tiny rectangles
that look broken.

Your translation is TEXT-ONLY:
  - Masthead: institution name typed centered, 12-14pt bold.
  - Signature block: officer name typed in normal weight.
    No signature image, no seal, no stamp.
  - Decoding tables, body paragraphs, course grids: text +
    real Word tables only. No image elements.

Ignore the EXTRACTED IMAGES list further below — it remains
in the prompt for back-compat but you must NOT use any of
those files in your output.

  * For an entry with kind=header → DO NOT insert any image here.
    The wrapper already embeds the full source PDF pages BEFORE
    your translation, so the original masthead (crest + ministry
    name) is preserved in the export. In YOUR translation body
    use a TEXT-ONLY masthead: a centered bold heading with the
    institution name typed out in {target_lang} at 12-14pt (e.g.
    "MINISTRY OF THE INTERIOR" or "UNIVERSITY OF FLORENCE"). NO
    crest image, NO logo image, NO low-res cropped strip. Just
    typed bold text.
  * For an entry with kind=footer → DO NOT paste this wide strip.
    Same problem — it's a low-res strip. Instead, rebuild the
    signature block in Word: officer name typed in normal weight
    above a signature image (width=Cm(5)) on the left, and the
    seal/stamp image (width=Cm(3)) on the right, in a borderless
    2-column table.
  * For an entry with kind=embedded → discrete extracted image
    (logo, photo, signature, seal). Place it where the source PDF
    shows it, sized appropriately per the sizing hints below.
  * Insert with `doc.add_picture("images/<filename>", width=Cm(N))`
    at the matching position.
  * STRICT SIZING — never exceed these widths for these element
    types (stretching small images to wider widths produces the
    blurry "broken image" effect):
      - crest / coat of arms      width=Cm(2.5)
      - institution logo          width=Cm(3)
      - round seal / rubber stamp width=Cm(3)
      - handwritten signature     width=Cm(5)
      - ID / passport photo       width=Cm(3) (set height instead)
      - watermark / background    skip (don't embed)
    For any other small image element, DO NOT set width=Cm(17) or
    width=Cm(15) — use Cm(3-5) max.
  * If the source is a flat scan (one big image per page rather
    than discrete logo/seal/signature image files), the
    EXTRACTED IMAGES list may be empty or only contain whole-page
    bitmaps. In that case use a short italic bracketed placeholder
    paragraph at the matching position (e.g. "[Logo]", "[Stamp]",
    "[Signature]") instead of trying to reference a file that
    isn't there.

ORDERING RULE: NEVER place a "CERTIFIED TRANSLATION" or affidavit-
style block at the START of the document. Your output ends with
the last piece of translated content — NO postscript, NO
translator's note, NO "this is a translation of..." sentence.

FORBIDDEN STRINGS — the following text must NOT appear anywhere in
your output:
  - "CERTIFIED TRANSLATION" (as a heading)
  - "I hereby certify" (or any variant)
  - "Translator:" followed by an email address
  - "Signature: ___" / "Date: <UTC date>" boilerplate
  - Any affidavit, certification, signature-line, or date-stamp
    block that resembles a translator's certification page.
  - "Note: This is an English translation of the original..." or
    any equivalent translator's-note sentence at the bottom.
  - "This document is an English translation of the original ..."
The official translator certification page is appended by the
wrapper AFTER your translation. Your job is ONLY the translation
body. Stop when the source's last paragraph is translated. Do
NOT add a closing remark.

VISUAL LAYOUT FIDELITY
======================
The output's PAGE LOOK must mirror the source page. Match the
source's column structure, alignment, and spacing — not a generic
left-aligned Word default. Specifically:

  * If the source has TWO labels on the SAME physical line (e.g.
    "Certificate No. XYZ" on the left and "Student ID No. 1234" on
    the right), the output MUST keep them on the SAME paragraph
    using a right-aligned tab stop. Example:

        from docx.enum.text import WD_TAB_ALIGNMENT
        pf = paragraph.paragraph_format
        pf.tab_stops.add_tab_stop(Cm(17), WD_TAB_ALIGNMENT.RIGHT)
        paragraph.add_run("Certificate No. XYZ")
        paragraph.add_run("\\t")
        paragraph.add_run("Student ID No. 1234")

  * Section dividers ("FIRST YEAR", "SECOND YEAR", "FINAL EXAM",
    etc.) MUST be centered if they are centered in the source.
    Use `p.alignment = WD_ALIGN_PARAGRAPH.CENTER`. Do NOT leave
    them as left-aligned headings.

  * The top-of-page header block (institutional logo + name)
    should match the source: if the source has logo at top-left
    and the institution name centered or right of the logo, use
    a 2-column borderless table where col 0 is the logo (Cm(3))
    and col 1 is the title text (Cm(14)), vertically centered.

  * Right-alignment matters: page numbers like "Page 1 of 2" or
    "Pagina 1 di 2", dates at the top right corner, and reference
    numbers at the top right MUST be right-aligned with
    `WD_ALIGN_PARAGRAPH.RIGHT` (or a right-aligned tab stop).

  * Match table column widths to the source PROPORTIONS. A narrow
    "Code" column should be ~2 cm, a wide "Course Name" column
    ~5 cm, "Grade" ~1.5 cm, etc. Don't make every column equal.
    Set widths AFTER add_table by writing
    `t.columns[i].width = Cm(N)` for each i.

  * Body paragraph spacing: use `Pt(2)` for space_after and
    `paragraph_format.line_spacing = 1.0` on every paragraph.
    Generic Word defaults insert too much vertical space and
    cause page-count drift.

  * Look at the actual pixel positions of text in the PDF and
    preserve the visual paragraph structure 1:1. If a paragraph
    is centered in the source, center it. If it's right-aligned,
    right-align it. If it's indented, indent it.

  * Match the FONT FAMILY and SIZE of the source when readable.
    FONT FLOOR: body text MUST be 11pt minimum (set explicitly
    via `run.font.size = Pt(11)`). NEVER drop below 10pt for body
    text — anything smaller looks unreadable. Headers and titles:
    12-14pt bold. Table content: 9-10pt acceptable if a wide
    table won't fit at 11pt, but only for table cell content,
    not body paragraphs. Footnotes / fine print at the very
    bottom of the document: 8pt.

  * BOLD WEIGHT — match the source's bold usage EXACTLY. Do NOT
    bold paragraphs that are regular weight in the source.
    Examples that should be regular (NOT bold) unless the source
    itself is bold:
      - Body paragraphs ("Dr. X, born on Y, passed the exam ...")
      - Two-label rows ("Cert. No. X" / "Student ID Y")
      - Page-position rows ("For Foreign Use" / "Page N of M")
      - All-caps centered statements ("HAVING EXAMINED THE
        OFFICIAL RECORDS, ... THAT") — these are regular weight
        in the source, just typographically all-caps.
    Bold belongs only on: real section headings ("FIRST YEAR",
    "PRIMO ANNO"), institutional masthead titles ("UNIVERSITÀ
    DEGLI STUDI FIRENZE"), and table column headers — and only
    when the source uses bold for those elements.

HARD RULES (never violate)
==========================
  * NEVER rotate text. NEVER set vertical text direction. All
    text in the output, in every paragraph and every table cell,
    must be normal horizontal left-to-right reading direction
    (right-to-left for Arabic / Hebrew / Farsi / Urdu targets).
  * If a wide table doesn't fit at 10-11pt on portrait A4, drop
    the font to 8pt or 7pt — never rotate column headers, never
    switch to landscape mid-document, never split sideways.
  * Use ONE consistent page orientation for the whole document
    unless the source mixes orientations.
  * Set table column widths explicitly with Cm() values that sum
    to ~17 cm for portrait A4 (page width minus 2cm margins).
  * The header block at the top of page 1 is full-width and
    horizontal.

Quality bar: imagine you (Claude) were asked directly by a user to
"translate this document and give me a Word file that looks like the
original". Produce that. The output should read like a human
translator typed it up in Word, not like a layout engine reflowed
it through tables.

EXTRACTED TABLES (verified by a Vision pre-pass — use VERBATIM)
================================================================
A Claude Vision pre-pass already read every data table on the source
PDF and returned them as structured JSON below. When building any
Word data table in your script, USE THESE JSON VALUES VERBATIM —
do NOT re-read the data from the PDF image, do NOT split or
recombine cells. Iterate the "headers" list to create the header
row, then iterate the "rows" list creating one row per entry and
populating cells[i].text = row[i] for each i.

If this section is empty, no data tables were detected and you can
build any table directly from the PDF.

HARD RULE — TABLES MUST USE doc.add_table()
============================================
For EVERY entry in EXTRACTED TABLES below, you MUST emit a real
Word table via `doc.add_table(rows=N, cols=M)` and populate
cells[i][j].text = row[i][j]. DO NOT render tabular data as a
flat list of paragraphs ("30610002\\nADMINISTRATIVE LAW\\nPassed\\n
29/30\\n6\\nIUS/10\\n..."). That breaks the visual structure and
the output looks nothing like the source.

The minimum recipe for ANY data table:

    t = doc.add_table(rows=1, cols=len(headers))
    t.autofit = False
    t.allow_autofit = False
    # Headers
    hdr_cells = t.rows[0].cells
    for j, h in enumerate(headers):
        p = hdr_cells[j].paragraphs[0]
        run = p.add_run(h)
        run.bold = True
        run.font.size = Pt(9)
    # Data rows
    for row in rows:
        row_cells = t.add_row().cells
        for j, val in enumerate(row):
            p = row_cells[j].paragraphs[0]
            run = p.add_run(str(val))
            run.font.size = Pt(9)
    # Borderless layout — strip every border, every edge.
    for cell in t._cells:
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = OxmlElement('w:tcBorders')
        for edge_name in ('top','left','bottom','right','insideH','insideV'):
            b = OxmlElement('w:' + edge_name)
            b.set(qn('w:val'), 'nil')
            tcBorders.append(b)
        tcPr.append(tcBorders)
    # Column widths sized to the source's proportions:
    # narrow code column, wide name column, medium for grade/date.
    # Adjust based on the actual table — sum should be ~17cm A4.

{table_list}

EXTRACTED IMAGES
================
{image_list}

Begin your code block now.
""").strip()


# Modules we let the sandbox script access. python-docx itself
# imports a handful of stdlib things (io, zipfile, copy, pathlib,
# etc.) so we don't try to remove those — we only block obvious
# escape hatches (subprocess, socket, requests, urllib, etc.) by
# patching them out at the top of the script we execute.
_SANDBOX_PREAMBLE = textwrap.dedent('''
    # --- Sandbox preamble (injected by claude_authored_rebuild) ---
    # Strip out network / shell escape modules before user code runs.
    import sys as _sys
    # Only block modules that actually open network sockets or
    # spawn shells. urllib.parse, urllib, http, ctypes are NOT
    # blocked because lxml (a python-docx dep) imports them
    # internally for XML namespace / URI parsing.
    _BLOCKED = (
        "socket", "ssl",
        "ftplib", "telnetlib", "smtplib", "poplib", "imaplib",
        "urllib.request", "http.client",
        "requests", "httpx",
        "subprocess", "multiprocessing", "asyncio.subprocess",
    )
    for _m in _BLOCKED:
        _sys.modules[_m] = None  # raises ImportError on `import`
    # --- end preamble ---
''').strip() + "\n\n"


def _strip_code_fence(text: str) -> str:
    """Pull the inner Python source out of a ```python ... ``` block.

    Claude sometimes wraps the script in a fenced block, sometimes
    returns it raw. Handle both.
    """
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # No fence — assume it's raw code.
    return text.strip()


def _validate_script(script: str, output_path: str) -> None:
    """Reject scripts that won't save to the agreed path or that try
    to do something obviously unsafe.

    We're not aiming for hermetic sandboxing — we're aiming to catch
    "Claude forgot to call doc.save" and "Claude invented a different
    output filename" before we burn the subprocess.
    """
    if "Document(" not in script and "docx" not in script:
        raise ValueError("Script doesn't appear to use python-docx")
    if output_path not in script:
        raise ValueError(
            f"Script doesn't write to OUTPUT_PATH ({output_path}). "
            "Refusing to execute — would silently produce no DOCX."
        )
    if "doc.save" not in script and ".save(" not in script:
        raise ValueError("Script never calls .save()")
    # Cheap blocklist — the sandbox preamble also handles these but
    # rejecting early gives a clearer error.
    for forbidden in ("subprocess", "socket.", "urllib", "requests.", "os.system"):
        if forbidden in script:
            raise ValueError(f"Script references blocked module: {forbidden}")


def _extract_pdf_images(pdf_bytes: bytes, dest_dir: Path) -> list:
    """Extract images from a PDF, with a fallback for flat scans.

    Tries two strategies per page:

      1. `page.get_images(full=True)` — finds embedded XObjects.
         Works on vector PDFs that have logos / stamps as
         separate image streams.
      2. When (1) finds nothing on a page, the page is treated as
         a flat scan: we crop the masthead strip (top 28% of the
         page) and the signature strip (bottom 25% of the LAST
         page) as separate PNGs. That gives Claude real logo /
         seal / signature bitmaps to insert via doc.add_picture
         instead of falling back to "[Coat of Arms]" placeholders.

    Returns dicts the prompt then formats:
        {"filename": "...", "page": N,
         "width_px": W, "height_px": H, "kind": "embedded"|"header"|"footer"}

    Failures are non-fatal — we return whatever we got.
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        logger.warning("PyMuPDF (fitz) not installed — skipping image extraction")
        return []

    images_dir = dest_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    out = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.warning("Failed to open PDF for image extraction: %s", e)
        return []

    try:
        n_pages = len(doc)
        for page_num, page in enumerate(doc, start=1):
            embedded_count = 0
            # Strategy 1: embedded XObjects. Skip page-sized
            # images — those are usually scanned-page bitmaps, not
            # discrete logos, and Claude inserting them produces the
            # "screenshot of the whole page" output the user keeps
            # seeing. Threshold: image must be < 60% of the page
            # area to be considered a discrete asset.
            page_rect = page.rect
            page_area = max(1.0, page_rect.width * page_rect.height)
            for img_idx, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n - pix.alpha >= 4:  # CMYK -> convert to RGB
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    # Reject images that are too large (page scans).
                    img_area_pts = (pix.width * pix.height) / (3 * 3)  # we extract at 3x earlier but get_images is at PDF-native
                    # Use raw pixmap dims vs page dims (both in pts).
                    if pix.width >= page_rect.width * 0.85 and pix.height >= page_rect.height * 0.6:
                        logger.info(
                            "Skipping page-sized embedded image p%d idx%d (%dx%d vs page %dx%d)",
                            page_num, img_idx, pix.width, pix.height,
                            int(page_rect.width), int(page_rect.height),
                        )
                        pix = None
                        continue
                    fname = f"p{page_num}_img{img_idx}.png"
                    fpath = images_dir / fname
                    pix.save(str(fpath))
                    out.append({
                        "filename": fname,
                        "page": page_num,
                        "width_px": pix.width,
                        "height_px": pix.height,
                        "kind": "embedded",
                    })
                    embedded_count += 1
                    pix = None
                except Exception as e:
                    logger.warning(
                        "Skipped image p%d idx%d: %s", page_num, img_idx, e
                    )

            # Strategy 2: flat-scan fallback. If the page has no
            # embedded images AND the page is large enough to be a
            # full doc page (not a thumbnail), crop header / footer.
            if embedded_count == 0:
                try:
                    rect = page.rect
                    page_w, page_h = rect.width, rect.height
                    if page_w < 100 or page_h < 100:
                        continue
                    # Header crop: top 16% — tight to the actual
                    # logo area. 28% was too generous and included
                    # the whole institution-name band, producing
                    # "looks like a screenshot of the page header"
                    # output. 16% is just the crest + immediate
                    # vicinity. Adjust per-document if needed.
                    header_clip = fitz.Rect(
                        0, 0, page_w, page_h * 0.16
                    )
                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(3, 3),  # 3x for crispness
                        clip=header_clip,
                        alpha=False,
                    )
                    fname = f"p{page_num}_header.png"
                    fpath = images_dir / fname
                    pix.save(str(fpath))
                    out.append({
                        "filename": fname,
                        "page": page_num,
                        "width_px": pix.width,
                        "height_px": pix.height,
                        "kind": "header",
                    })
                    pix = None

                    # Footer crop: only on the LAST page (signature
                    # block + stamp typically live there).
                    if page_num == n_pages:
                        footer_clip = fitz.Rect(
                            0, page_h * 0.62, page_w, page_h * 0.80
                        )
                        pix = page.get_pixmap(
                            matrix=fitz.Matrix(3, 3),
                            clip=footer_clip,
                            alpha=False,
                        )
                        fname = f"p{page_num}_footer.png"
                        fpath = images_dir / fname
                        pix.save(str(fpath))
                        out.append({
                            "filename": fname,
                            "page": page_num,
                            "width_px": pix.width,
                            "height_px": pix.height,
                            "kind": "footer",
                        })
                        pix = None
                except Exception as e:
                    logger.warning(
                        "Flat-scan crop fallback failed on page %d: %s",
                        page_num, e,
                    )
    finally:
        try:
            doc.close()
        except Exception:
            pass

    logger.info(
        "Extracted %d image(s) from PDF (%d embedded, %d scan crops)",
        len(out),
        sum(1 for x in out if x.get("kind") == "embedded"),
        sum(1 for x in out if x.get("kind") in ("header", "footer")),
    )
    return out


def _format_image_list(images: list) -> str:
    """Render the extracted-image list as bullet lines for the prompt."""
    if not images:
        return "(no images extracted — use bracketed placeholders)"
    lines = []
    kind_hint = {
        "header": "likely contains logo + masthead — crop or use as-is",
        "footer": "likely contains signature + seal + stamp — crop or use as-is",
        "embedded": "discrete embedded image",
    }
    for im in images:
        kind = im.get("kind", "embedded")
        hint = kind_hint.get(kind, "")
        lines.append(
            f'  - images/{im["filename"]}  (page {im["page"]}, '
            f'{im["width_px"]}x{im["height_px"]} px, {kind}{": " + hint if hint else ""})'
        )
    return "\n".join(lines)



def _extract_tables_via_vision(
    pdf_bytes: bytes,
    model: str = "claude-opus-4-6",
) -> list:
    """Pre-pass: render each page of the PDF as an image and ask
    Claude Vision to extract any data tables as structured JSON.

    Returns a list of dicts:
        [{"page": 1, "title": "FIRST YEAR",
          "headers": ["Course Code","Course","Outcome",...],
          "rows": [["30610002","ADMINISTRATIVE LAW","Passed",...], ...]},
         ...]

    Empty list if no tables detected or the call fails. This list is
    embedded into the author prompt under EXTRACTED TABLES so the
    author script can paste cell values verbatim instead of trying
    to OCR them itself.
    """
    try:
        import json as _json
        import anthropic  # type: ignore
        import fitz
    except Exception:
        logger.warning("Vision table extraction unavailable (missing dep)")
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.warning("Vision table pre-pass: PDF open failed: %s", e)
        return []

    page_imgs_b64 = []
    try:
        for p in doc:
            try:
                pix = p.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                page_imgs_b64.append(
                    base64.standard_b64encode(pix.tobytes("png")).decode("ascii")
                )
            except Exception as e:
                logger.warning("Vision pre-pass page render failed: %s", e)
    finally:
        try:
            doc.close()
        except Exception:
            pass

    if not page_imgs_b64:
        return []

    client = anthropic.Anthropic(api_key=api_key)

    EXTRACT_PROMPT = textwrap.dedent("""
        Look at the attached PDF page image(s). Identify every data
        table on every page — a "data table" is a multi-row grid of
        values like a courses/grades list, an invoice line-items
        block, a price list, a schedule, etc. Single-row layout
        tables (logo|name header, label|value pairs) DO NOT count.

        For each real data table, return a JSON object with these
        fields:
            "page": <1-indexed page number>
            "title": <the heading immediately above the table,
                       e.g. "FIRST YEAR", or "" if none>
            "headers": <list of column header strings, in left-to-
                        right order>
            "rows": <list of rows, each row a list of cell values in
                     left-to-right order, ONE value per cell>

        Read each row CAREFULLY column by column. Course codes,
        outcomes ("Passed"/"Failed"), grades ("29/30"), credit
        counts, sector codes (e.g. "IUS/10"), dates and trailing
        identifiers MUST land in separate cells.

        Return ONE JSON object wrapped in ```json … ```:
            {"tables": [ {...}, {...}, ... ]}

        Empty array if no real data tables exist. No prose. No
        commentary. Just the JSON block.
    """).strip()

    content = []
    for b64 in page_imgs_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            },
        })
    content.append({"type": "text", "text": EXTRACT_PROMPT})

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            temperature=0.1,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:
        logger.warning("Vision table extraction call failed: %s", e)
        return []

    raw = ""
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            raw += getattr(block, "text", "") or ""

    # Pull the JSON out of a fenced block if present.
    m = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    payload = m.group(1).strip() if m else raw.strip()
    try:
        data = _json.loads(payload)
    except Exception:
        logger.warning(
            "Vision table extraction returned non-JSON: %r", raw[:300]
        )
        return []

    tables = data.get("tables", []) if isinstance(data, dict) else []
    cleaned = []
    for t in tables:
        if not isinstance(t, dict):
            continue
        headers = t.get("headers") or []
        rows = t.get("rows") or []
        if not isinstance(headers, list) or not isinstance(rows, list):
            continue
        cleaned.append({
            "page": int(t.get("page", 0) or 0),
            "title": str(t.get("title", "") or ""),
            "headers": [str(h) for h in headers],
            "rows": [[str(c) for c in r] for r in rows if isinstance(r, list)],
        })
    logger.info(
        "Vision table extraction: %d table(s), %d total rows",
        len(cleaned),
        sum(len(t["rows"]) for t in cleaned),
    )
    return cleaned


def _format_table_list(tables: list) -> str:
    """Render the EXTRACTED TABLES block for the author prompt."""
    if not tables:
        return "(no data tables detected by vision pre-pass)"
    import json as _json
    return _json.dumps({"tables": tables}, indent=2, ensure_ascii=False)


def _call_claude_to_author(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    output_path: str,
    images: list,
    tables: list,
    model: str = "claude-opus-4-6",
) -> str:
    """Send the PDF + prompt to Claude and return the raw code block.

    We use Claude Sonnet (the same family that powers Claude.ai) and
    pass the PDF as a `document` content block — the SDK's native
    way of attaching PDFs. We allow up to 16k output tokens because
    big layouts produce big scripts.
    """
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "anthropic SDK not installed — cannot run authored rebuild"
        ) from e

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — cannot run authored rebuild"
        )

    client = anthropic.Anthropic(api_key=api_key)

    prompt = _AUTHOR_PROMPT_TEMPLATE.format(
        source_lang=source_lang or "the source language",
        target_lang=target_lang,
        output_path=output_path,
        image_list=_format_image_list(images),
        table_list=_format_table_list(tables),
    )

    logger.info(
        "Calling Claude (model=%s) for authored rebuild "
        "(pdf_bytes=%d, source=%s, target=%s)",
        model, len(pdf_bytes), source_lang, target_lang,
    )

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")

    # Fallback chain: try Opus 4.6 first, then Sonnet 4.6, then
    # Sonnet 4.5 (known-good legacy). Each fallback is triggered on
    # 404 / model-not-found / overloaded / server-error responses.
    model_chain = [model, "claude-sonnet-4-6", "claude-sonnet-4-5-20250929"]
    seen = set()
    model_chain = [m for m in model_chain if m and not (m in seen or seen.add(m))]

    def _try_call(attempt_model, use_thinking):
        kwargs = {
            "model": attempt_model,
            "max_tokens": 64000 if use_thinking else 16000,
            "messages": [
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
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        if use_thinking:
            # Extended thinking is the same mechanism Claude.ai uses
            # for hard PDFs. Requires temperature=1.0.
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 20000}
            kwargs["temperature"] = 1.0
        else:
            kwargs["temperature"] = 0.2
        return client.messages.create(**kwargs)

    last_exc = None
    resp = None
    used_model = None
    used_thinking = None
    for attempt_model in model_chain:
        for use_thinking in (True, False):
            try:
                resp = _try_call(attempt_model, use_thinking)
                used_model = attempt_model
                used_thinking = use_thinking
                break
            except Exception as e:
                msg = str(e).lower()
                last_exc = e
                # LOG THE FULL ERROR so we can diagnose.
                logger.warning(
                    "Claude API call failed (model=%s, thinking=%s): %s",
                    attempt_model, use_thinking, e,
                )
                # Thinking-specific failures → retry without thinking
                # on the SAME model before moving to the next model.
                if use_thinking and any(s in msg for s in (
                    "thinking", "extended_thinking", "budget_tokens",
                    "temperature", "invalid_request", "400",
                )):
                    logger.info("Retrying without extended thinking…")
                    continue
                # Model-not-found / overload / 5xx → move to next model.
                if any(s in msg for s in (
                    "404", "not_found", "model_not_found",
                    "overloaded", "rate_limit", "503", "500", "529",
                )):
                    break  # next model
                # Anything else (auth, malformed request) — bubble up.
                raise
        if resp is not None:
            break

    if resp is None:
        raise RuntimeError(
            f"All Claude models in fallback chain failed: {last_exc}"
        )

    logger.info(
        "Claude succeeded with model=%s, thinking=%s",
        used_model, used_thinking,
    )

    # Walk the content blocks. With thinking enabled there may be
    # "thinking" blocks before the actual "text" output — skip those.
    text_blocks = []
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            text_blocks.append(getattr(block, "text", "") or "")
    raw = "\n".join(text_blocks)
    logger.info(
        "Claude (%s, thinking=%s) returned %d chars (usage in=%d out=%d)",
        used_model, used_thinking, len(raw),
        getattr(resp.usage, "input_tokens", -1),
        getattr(resp.usage, "output_tokens", -1),
    )
    return raw


def _run_script_in_sandbox(
    script: str,
    output_path: str,
    timeout_seconds: int = 300,
) -> bytes:
    """Run Claude's script in a subprocess and return the DOCX bytes.

    We prepend a small preamble that NULs out the obvious escape
    modules. The subprocess inherits the worker's PYTHONPATH so it
    can find python-docx. stdout/stderr are captured for logging.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="claude_authored_"))
    # If the caller extracted images into <output_dir>/images, mirror
    # them into work_dir/images so the script can resolve relative
    # paths like "images/p1_img0.png" with its cwd set to work_dir.
    try:
        out_dir = Path(output_path).parent
        src_images_dir = out_dir / "images"
        if src_images_dir.exists() and src_images_dir.is_dir():
            dst_images_dir = work_dir / "images"
            shutil.copytree(src_images_dir, dst_images_dir)
    except Exception as e:
        logger.warning("Failed to mirror images into work_dir: %s", e)

    try:
        script_path = work_dir / "rebuild.py"
        # Write the preamble + user code.
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(_SANDBOX_PREAMBLE)
            f.write(script)
            f.write("\n")

        cmd = [sys.executable, str(script_path)]
        # -I: isolate (ignore PYTHONPATH env, user site-packages)
        # -S: don't run site.py
        # We do want python-docx, so we set PYTHONPATH back to the
        # parent process's sys.path explicitly.
        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": os.pathsep.join(sys.path),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

        logger.info("Running authored-rebuild script in %s", work_dir)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            env=env,
            cwd=str(work_dir),
            timeout=timeout_seconds,
        )

        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
            stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
            logger.error(
                "Authored-rebuild script failed (rc=%d)\n"
                "STDOUT:\n%s\n\nSTDERR:\n%s",
                proc.returncode, stdout[-2000:], stderr[-2000:],
            )
            raise RuntimeError(
                f"Authored rebuild script exited with code {proc.returncode}: "
                f"{stderr.strip().splitlines()[-1] if stderr else 'unknown error'}"
            )

        out = Path(output_path)
        if not out.exists():
            raise RuntimeError(
                f"Script ran but didn't produce {output_path}"
            )
        return out.read_bytes()

    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Authored rebuild timed out after {timeout_seconds}s"
        )
    finally:
        # Clean up the work directory but keep the produced DOCX
        # since output_path points outside work_dir.
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass


def _strip_rotation_from_docx(docx_bytes: bytes) -> bytes:
    """Remove any vertical-text / rotation properties from a DOCX.

    Walks word/document.xml in the zip, deletes every <w:textDirection>
    element (which is how Word records rotated cells / sections), then
    rewrites the zip. This is a deterministic safety net against
    Claude regressing on the "no rotation" prompt rule.

    Failures are non-fatal — we return the original bytes on any error.
    """
    try:
        import io
        import zipfile
        from xml.etree import ElementTree as ET

        # Word XML namespaces.
        W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ET.register_namespace("w", W_NS)
        TD_TAG = "{%s}textDirection" % W_NS

        in_buf = io.BytesIO(docx_bytes)
        out_buf = io.BytesIO()
        modified = False

        with zipfile.ZipFile(in_buf, "r") as zin:
            with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    # Only patch word/document.xml — sectPr / cells live there.
                    if item.filename == "word/document.xml":
                        try:
                            root = ET.fromstring(data)
                            removed = 0
                            # ElementTree doesn't support arbitrary
                            # ancestor lookup, so walk all elements and
                            # remove every textDirection from its parent.
                            parent_map = {c: p for p in root.iter() for c in p}
                            for el in list(root.iter(TD_TAG)):
                                parent = parent_map.get(el)
                                if parent is not None:
                                    parent.remove(el)
                                    removed += 1
                            if removed:
                                data = ET.tostring(
                                    root,
                                    xml_declaration=True,
                                    encoding="UTF-8",
                                    short_empty_elements=True,
                                )
                                logger.info(
                                    "Stripped %d rotation directives from DOCX",
                                    removed,
                                )
                                modified = True
                        except Exception as e:
                            logger.warning(
                                "Rotation-strip XML parse failed: %s", e
                            )
                    zout.writestr(item, data)

        if modified:
            return out_buf.getvalue()
        return docx_bytes
    except Exception:
        logger.exception("Rotation strip failed — returning original bytes")
        return docx_bytes


def _strip_layout_table_borders(docx_bytes: bytes) -> bytes:
    """Strip visible borders from EVERY table in the DOCX.

    The vast majority of source documents we handle (certificates,
    transcripts, official letters, IDs) use whitespace-aligned
    columns rather than visible cell borders. Stripping borders by
    default matches the source's appearance better than keeping
    them. Layout tables (logo|name header, label|value rows,
    signature blocks, decoding-key pairs) and data grids (courses,
    invoice line items) all become borderless.

    If a future use case requires visible borders, the
    `_strip_all_borders` parameter can be flipped off — but the
    deterministic borderless behaviour is preferred because Claude
    can't reliably detect when the source has borders vs not.
    """
    try:
        import io
        import zipfile
        from xml.etree import ElementTree as ET

        W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ET.register_namespace("w", W_NS)
        ns = {"w": W_NS}

        in_buf = io.BytesIO(docx_bytes)
        out_buf = io.BytesIO()
        modified = False

        with zipfile.ZipFile(in_buf, "r") as zin:
            with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    # Belt-and-braces: patch styles.xml so the
                    # default "Table Grid" / "TableGrid" style is
                    # borderless. That way even if document.xml has a
                    # <w:tblStyle w:val="TableGrid"/> reference we
                    # missed, the style itself contributes no borders.
                    if item.filename == "word/styles.xml":
                        try:
                            data_str = data.decode("utf-8")
                            # Find every <w:style w:type="table">
                            # block and force its tblBorders to nil.
                            new_data, n_styles = _force_borderless_table_styles(data_str, W_NS)
                            if n_styles:
                                data = new_data.encode("utf-8")
                                logger.info(
                                    "Forced %d table style(s) borderless in styles.xml",
                                    n_styles,
                                )
                                modified = True
                        except Exception as e:
                            logger.warning(
                                "styles.xml patch failed: %s", e
                            )
                    if item.filename == "word/document.xml":
                        try:
                            root = ET.fromstring(data)
                            stripped = 0
                            for tbl in root.iter("{%s}tbl" % W_NS):
                                # Strip borders from THREE sources:
                                #   1. <w:tblStyle> reference (e.g.
                                #      "Table Grid") — this is what
                                #      Claude usually emits; without
                                #      removing it, Word reads the
                                #      style definition from
                                #      styles.xml and draws borders
                                #      regardless of our tblBorders.
                                #   2. <w:tblBorders> directly on the
                                #      table — overrides style.
                                #   3. <w:tcBorders> on each cell —
                                #      cell-level overrides.
                                tblPr = tbl.find("{%s}tblPr" % W_NS)
                                if tblPr is None:
                                    tblPr = ET.SubElement(tbl, "{%s}tblPr" % W_NS)
                                    tbl.insert(0, tblPr)
                                # 1. Remove style reference so the
                                #    Table Grid style's borders don't
                                #    show through.
                                for s in tblPr.findall("{%s}tblStyle" % W_NS):
                                    tblPr.remove(s)
                                # 2. Force tblBorders to nil.
                                for b in tblPr.findall("{%s}tblBorders" % W_NS):
                                    tblPr.remove(b)
                                borders = ET.SubElement(tblPr, "{%s}tblBorders" % W_NS)
                                for edge in (
                                    "top", "left", "bottom", "right",
                                    "insideH", "insideV",
                                ):
                                    e = ET.SubElement(borders, "{%s}%s" % (W_NS, edge))
                                    e.set("{%s}val" % W_NS, "nil")
                                # 3. Clear per-cell borders AND add
                                #    explicit nil tcBorders so cells
                                #    don't inherit borders from any
                                #    surviving table style.
                                for tc in tbl.iter("{%s}tc" % W_NS):
                                    tcPr = tc.find("{%s}tcPr" % W_NS)
                                    if tcPr is None:
                                        tcPr = ET.SubElement(tc, "{%s}tcPr" % W_NS)
                                        tc.insert(0, tcPr)
                                    for b in tcPr.findall("{%s}tcBorders" % W_NS):
                                        tcPr.remove(b)
                                    tcb = ET.SubElement(tcPr, "{%s}tcBorders" % W_NS)
                                    for edge in (
                                        "top", "left", "bottom", "right",
                                    ):
                                        e = ET.SubElement(
                                            tcb, "{%s}%s" % (W_NS, edge)
                                        )
                                        e.set("{%s}val" % W_NS, "nil")
                                stripped += 1
                            if stripped:
                                data = ET.tostring(
                                    root,
                                    xml_declaration=True,
                                    encoding="UTF-8",
                                    short_empty_elements=True,
                                )
                                logger.info(
                                    "Stripped borders from %d tables (all-borderless mode)",
                                    stripped,
                                )
                                modified = True
                        except Exception as e:
                            logger.warning(
                                "Layout-table border strip failed: %s", e
                            )
                    zout.writestr(item, data)

        return out_buf.getvalue() if modified else docx_bytes
    except Exception:
        logger.exception("Layout-table border strip failed — returning original")
        return docx_bytes


def _split_crammed_table_rows(docx_bytes: bytes) -> bytes:
    """Find data tables where rows have 1 cell containing what should
    be N cells (matching the header row's column count) and split
    them.

    Heuristic: assume the LAST row is misformatted if its first cell's
    text reads like a concatenation of multiple column values. We
    split using a combination of:
        * known token regexes (8-digit code, date, grade, sector code)
        * separator detection (tabs, runs of 2+ spaces, |)

    Best-effort — leaves any row untouched if it can't confidently
    split into the expected number of cells.
    """
    try:
        import io
        import re
        import zipfile
        from xml.etree import ElementTree as ET

        W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ET.register_namespace("w", W_NS)

        # Patterns we use to detect column boundaries.
        TOKEN_RES = [
            re.compile(r"^\d{8}$"),                  # 8-digit ID
            re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"),  # date
            re.compile(r"^\d{1,3}/\d{1,3}$"),        # grade like 29/30
            re.compile(r"^[A-Z]{2,5}/\d{1,3}$"),     # sector code IUS/10
            re.compile(r"^Passed$|^Failed$|^Approved$", re.I),
        ]

        def _txt(el):
            return "".join(t.text or "" for t in el.iter("{%s}t" % W_NS))

        def _cells(row):
            return row.findall("{%s}tc" % W_NS)

        def _set_cell_text(cell, text):
            # Remove existing <w:p> children and add one fresh.
            for p in list(cell.findall("{%s}p" % W_NS)):
                cell.remove(p)
            new_p = ET.SubElement(cell, "{%s}p" % W_NS)
            new_r = ET.SubElement(new_p, "{%s}r" % W_NS)
            new_t = ET.SubElement(new_r, "{%s}t" % W_NS)
            new_t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            new_t.text = text

        def _add_empty_cell(row):
            new_tc = ET.SubElement(row, "{%s}tc" % W_NS)
            new_p = ET.SubElement(new_tc, "{%s}p" % W_NS)
            return new_tc

        def _smart_split(text, n_cols):
            """Split `text` into n_cols values using whitespace + token regexes."""
            tokens = text.split()
            if len(tokens) < n_cols:
                return None
            # Try greedy assignment from the right (the tail is usually
            # a multi-word field like "10 3061 PDS0-2019"). Use a
            # 2-pass approach: anchor known regex tokens to their
            # likely column, then fill the rest.
            # Simple approach: take first token as col 0, then walk
            # forward absorbing into the current column until the next
            # token matches a "boundary" regex.
            cols = []
            i = 0
            while i < len(tokens) and len(cols) < n_cols:
                # If this is the last column slot, absorb everything left.
                if len(cols) == n_cols - 1:
                    cols.append(" ".join(tokens[i:]))
                    break
                cur = tokens[i]
                i += 1
                # If cur matches a token regex it's a single-token column.
                if any(p.match(cur) for p in TOKEN_RES):
                    cols.append(cur)
                    continue
                # Otherwise absorb following non-boundary tokens.
                while i < len(tokens) and not any(p.match(tokens[i]) for p in TOKEN_RES):
                    cur = cur + " " + tokens[i]
                    i += 1
                cols.append(cur)
            if len(cols) == n_cols:
                return cols
            return None

        in_buf = io.BytesIO(docx_bytes)
        out_buf = io.BytesIO()
        modified = False

        with zipfile.ZipFile(in_buf, "r") as zin:
            with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    # Belt-and-braces: patch styles.xml so the
                    # default "Table Grid" / "TableGrid" style is
                    # borderless. That way even if document.xml has a
                    # <w:tblStyle w:val="TableGrid"/> reference we
                    # missed, the style itself contributes no borders.
                    if item.filename == "word/styles.xml":
                        try:
                            data_str = data.decode("utf-8")
                            # Find every <w:style w:type="table">
                            # block and force its tblBorders to nil.
                            new_data, n_styles = _force_borderless_table_styles(data_str, W_NS)
                            if n_styles:
                                data = new_data.encode("utf-8")
                                logger.info(
                                    "Forced %d table style(s) borderless in styles.xml",
                                    n_styles,
                                )
                                modified = True
                        except Exception as e:
                            logger.warning(
                                "styles.xml patch failed: %s", e
                            )
                    if item.filename == "word/document.xml":
                        try:
                            root = ET.fromstring(data)
                            split_count = 0
                            for tbl in root.iter("{%s}tbl" % W_NS):
                                rows = tbl.findall("{%s}tr" % W_NS)
                                if len(rows) < 2:
                                    continue
                                header = rows[0]
                                n_cols = len(_cells(header))
                                if n_cols < 4:
                                    continue  # too small to bother
                                for row in rows[1:]:
                                    cells = _cells(row)
                                    cell_texts = [_txt(c).strip() for c in cells]
                                    non_empty_indices = [
                                        i for i, t in enumerate(cell_texts) if t
                                    ]
                                    # Case A: row already has data spread
                                    # across multiple cells → leave alone.
                                    if len(non_empty_indices) >= max(2, n_cols // 2):
                                        continue
                                    # Case B: row has no text anywhere → skip.
                                    if not non_empty_indices:
                                        continue
                                    # Case C: row has text only in cell 0
                                    # (or one cell), and that cell's text
                                    # reads like a concatenation of N column
                                    # values. Split it.
                                    text_cell_idx = non_empty_indices[0]
                                    text = cell_texts[text_cell_idx]
                                    parts = _smart_split(text, n_cols)
                                    if not parts:
                                        continue
                                    # Distribute across cells: write parts[0]
                                    # into the cell that had the text,
                                    # parts[1:] into the rest (creating new
                                    # cells if needed).
                                    _set_cell_text(cells[text_cell_idx], parts[0])
                                    rest = parts[1:]
                                    # Fill any subsequent existing empty cells
                                    # first, then append new ones.
                                    next_idx = text_cell_idx + 1
                                    for value in rest:
                                        if next_idx < len(cells):
                                            _set_cell_text(cells[next_idx], value)
                                            next_idx += 1
                                        else:
                                            new_tc = _add_empty_cell(row)
                                            _set_cell_text(new_tc, value)
                                    split_count += 1
                            if split_count:
                                data = ET.tostring(
                                    root,
                                    xml_declaration=True,
                                    encoding="UTF-8",
                                    short_empty_elements=True,
                                )
                                logger.info(
                                    "Split %d crammed table rows", split_count
                                )
                                modified = True
                        except Exception as e:
                            logger.warning(
                                "Row-split post-processor failed: %s", e
                            )
                    zout.writestr(item, data)

        return out_buf.getvalue() if modified else docx_bytes
    except Exception:
        logger.exception("Row-split failed — returning original")
        return docx_bytes


def _replace_image_placeholders(docx_bytes: bytes, work_dir: Path) -> bytes:
    """Replace bracketed text placeholders with actual extracted
    images.

    Looks for "[Coat of Arms]" / "[Logo]" / "[Stamp]" / "[Signature]"
    / "[Photo]" / "[Seal]" / "[Crest]" text in the DOCX. For each
    match, picks the most suitable extracted image (logo-like for
    [Coat of Arms]/[Logo]/[Crest], footer-crop for [Stamp]/[Signature]
    /[Seal], any embedded for [Photo]) and inlines it via python-docx.

    `work_dir` is the same out_dir we passed to _extract_pdf_images,
    so images live at work_dir/images/<filename>.
    """
    try:
        import io
        import re as _re
        from io import BytesIO
        from docx import Document
        from docx.shared import Cm

        images_dir = Path(work_dir) / "images"
        if not images_dir.exists():
            return docx_bytes

        all_imgs = sorted(images_dir.glob("*.png")) + sorted(images_dir.glob("*.jpg")) + sorted(images_dir.glob("*.jpeg"))
        if not all_imgs:
            return docx_bytes

        # Categorize available images by filename hints.
        headers = [p for p in all_imgs if "header" in p.name]
        footers = [p for p in all_imgs if "footer" in p.name]
        embedded = [p for p in all_imgs if "img" in p.name and "header" not in p.name and "footer" not in p.name]

        def _pick(placeholder: str):
            ph = placeholder.lower()
            if any(k in ph for k in ("coat", "logo", "crest", "arms")):
                return (headers + embedded + footers)[0] if (headers + embedded + footers) else None
            if any(k in ph for k in ("stamp", "seal", "signature", "sigillum")):
                return (footers + embedded + headers)[0] if (footers + embedded + headers) else None
            if "photo" in ph:
                return (embedded + headers + footers)[0] if (embedded + headers + footers) else None
            return None

        # Size hints in cm.
        def _width(placeholder: str) -> float:
            ph = placeholder.lower()
            if any(k in ph for k in ("coat", "logo", "crest", "arms")):
                return 3.5
            if "stamp" in ph or "seal" in ph:
                return 3.0
            if "signature" in ph:
                return 5.0
            if "photo" in ph:
                return 3.0
            return 4.0

        PATTERN = _re.compile(
            r"\[(?:Coat\s*of\s*Arms|Logo|Crest|Arms|Stamp|Seal|Signature|Photo)\]",
            _re.IGNORECASE,
        )

        doc = Document(BytesIO(docx_bytes))
        replaced = 0

        def _process_paragraph(para):
            """If this paragraph contains a placeholder, replace it
            with an image inline."""
            nonlocal replaced
            full_text = "".join(r.text or "" for r in para.runs)
            m = PATTERN.search(full_text)
            if not m:
                return
            placeholder = m.group(0)
            img_path = _pick(placeholder)
            if not img_path:
                return
            # Strip the placeholder from the text.
            new_text = full_text[:m.start()] + full_text[m.end():]
            # Clear existing runs.
            for r in list(para.runs):
                r._element.getparent().remove(r._element)
            # If there was surrounding text, re-add it.
            if new_text.strip():
                # Split around the placeholder spot (if before/after text)
                before = full_text[:m.start()]
                after = full_text[m.end():]
                if before:
                    para.add_run(before)
                run = para.add_run()
                run.add_picture(str(img_path), width=Cm(_width(placeholder)))
                if after:
                    para.add_run(after)
            else:
                run = para.add_run()
                run.add_picture(str(img_path), width=Cm(_width(placeholder)))
            replaced += 1

        # Walk body paragraphs.
        for para in doc.paragraphs:
            _process_paragraph(para)
        # Walk tables.
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        _process_paragraph(para)
        # Walk header / footer of every section.
        for section in doc.sections:
            for para in section.header.paragraphs:
                _process_paragraph(para)
            for para in section.footer.paragraphs:
                _process_paragraph(para)
            for tbl in section.header.tables:
                for row in tbl.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            _process_paragraph(para)
            for tbl in section.footer.tables:
                for row in tbl.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            _process_paragraph(para)

        if replaced:
            logger.info("Replaced %d image placeholder(s) with real images", replaced)
            buf = BytesIO()
            doc.save(buf)
            return buf.getvalue()
        return docx_bytes
    except Exception:
        logger.exception("Image-placeholder replace failed — returning original")
        return docx_bytes


def _strip_inline_cert_blocks(docx_bytes: bytes) -> bytes:
    """Remove certification-style paragraphs that Claude may have
    written INSIDE the translation body.

    Claude sometimes generates a "CERTIFIED TRANSLATION" affidavit
    at the start of its output despite the prompt rule, mimicking
    the hardcoded cert format. The wrapper appends the real cert
    AFTER the body, so any cert-style text inside Claude's body is a
    duplicate that needs to be stripped.

    Matches paragraphs whose text contains any of:
      - "CERTIFIED TRANSLATION" (case-insensitive, as a heading)
      - "I hereby certify"
      - "Translator: <email>"
      - "Signature: ___"
      - "Date: YYYY-MM-DD HH:MM UTC"

    Strips the matched paragraph PLUS any contiguous block of
    paragraphs around it that look like the affidavit boilerplate.

    Failures are non-fatal — returns the original bytes on any error.
    """
    try:
        import io as _io
        import re as _re
        import zipfile as _zip
        from xml.etree import ElementTree as ET

        W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ET.register_namespace("w", W_NS)
        P_TAG = "{%s}p" % W_NS
        T_TAG = "{%s}t" % W_NS

        FORBIDDEN_PATTERNS = [
            _re.compile(r"\bCERTIFIED\s+TRANSLATION\b", _re.I),
            _re.compile(r"\bI\s+hereby\s+certify\b", _re.I),
            _re.compile(r"^\s*Translator\s*:\s*\S+@\S+", _re.I),
            _re.compile(r"^\s*Signature\s*:\s*_+", _re.I),
            _re.compile(r"^\s*Date\s*:\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+UTC", _re.I),
            _re.compile(r"this\s+translation\s+is\s+accurate\s+and\s+complete", _re.I),
            # User-rejected translator's-note variants. Strip these
            # if Claude emits them despite the FORBIDDEN STRINGS rule.
            _re.compile(r"\bNote\s*:\s*This\s+(is|document)\s+(an|a)?\s*\w*\s*translation\b", _re.I),
            _re.compile(r"\bThis\s+document\s+is\s+(an|a)\s+\w+\s+translation\s+of\s+the\s+original\b", _re.I),
            _re.compile(r"\bcrest,?\s+seal\s+and\s+signature\s+are\s+reproduced\s+from\s+the\s+original\b", _re.I),
        ]

        TBL_TAG = "{%s}tbl" % W_NS
        TR_TAG = "{%s}tr" % W_NS
        TC_TAG = "{%s}tc" % W_NS

        def _para_text(el):
            return "".join(t.text or "" for t in el.iter(T_TAG)).strip()

        def _matches_forbidden(text):
            return any(p.search(text) for p in FORBIDDEN_PATTERNS)

        def _build_parent_map(root):
            return {child: parent for parent in root.iter() for child in parent}

        in_buf = _io.BytesIO(docx_bytes)
        out_buf = _io.BytesIO()
        modified = False

        with _zip.ZipFile(in_buf, "r") as zin:
            with _zip.ZipFile(out_buf, "w", _zip.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "word/document.xml":
                        try:
                            root = ET.fromstring(data)
                            removed = 0

                            # Recursive sweep: collect every w:p
                            # whose extracted text matches a
                            # forbidden pattern, anywhere in the
                            # document (top-level body, inside
                            # tables, inside nested tables — all
                            # of it).
                            parent_map = _build_parent_map(root)
                            paras_to_remove = []
                            for p in root.iter(P_TAG):
                                txt = _para_text(p)
                                if not txt:
                                    continue
                                if _matches_forbidden(txt):
                                    paras_to_remove.append(p)

                            # Also sweep neighbours of each matched
                            # paragraph in its parent's child list
                            # — picks up the "Signature: ___" and
                            # blank padding paragraphs around a
                            # matched "CERTIFIED TRANSLATION"
                            # heading even if the neighbour itself
                            # only matches a softer rule.
                            extra = set()
                            for p in paras_to_remove:
                                parent = parent_map.get(p)
                                if parent is None:
                                    continue
                                sibs = list(parent)
                                try:
                                    idx = sibs.index(p)
                                except ValueError:
                                    continue
                                # Backward sweep.
                                j = idx - 1
                                while j >= 0 and sibs[j].tag == P_TAG:
                                    t = _para_text(sibs[j])
                                    if not t:
                                        extra.add(sibs[j])
                                        j -= 1
                                        continue
                                    if _matches_forbidden(t):
                                        extra.add(sibs[j])
                                        j -= 1
                                    else:
                                        break
                                # Forward sweep.
                                k = idx + 1
                                while k < len(sibs) and sibs[k].tag == P_TAG:
                                    t = _para_text(sibs[k])
                                    if not t:
                                        extra.add(sibs[k])
                                        k += 1
                                        continue
                                    if _matches_forbidden(t):
                                        extra.add(sibs[k])
                                        k += 1
                                    else:
                                        break

                            all_to_remove = set(paras_to_remove) | extra
                            for p in all_to_remove:
                                parent = parent_map.get(p)
                                if parent is None:
                                    continue
                                try:
                                    parent.remove(p)
                                    removed += 1
                                except ValueError:
                                    pass

                            # After paragraph removal, sweep up
                            # empty containers: a w:tc with no
                            # remaining w:p — give it one blank
                            # para (Word requires every cell to
                            # contain at least one paragraph).
                            # A w:tr with all empty/cert-only
                            # cells, and a w:tbl with no rows,
                            # get removed entirely.
                            # Rebuild parent map because removals
                            # may have shifted things.
                            parent_map = _build_parent_map(root)
                            # Drop empty rows.
                            for tr in list(root.iter(TR_TAG)):
                                has_meaningful = False
                                for tc in tr.iter(TC_TAG):
                                    for p in tc.iter(P_TAG):
                                        if _para_text(p):
                                            has_meaningful = True
                                            break
                                    if has_meaningful:
                                        break
                                if not has_meaningful:
                                    parent = parent_map.get(tr)
                                    if parent is not None:
                                        try:
                                            parent.remove(tr)
                                        except ValueError:
                                            pass
                            # Drop empty tables.
                            parent_map = _build_parent_map(root)
                            for tbl in list(root.iter(TBL_TAG)):
                                rows = list(tbl.iter(TR_TAG))
                                if not rows:
                                    parent = parent_map.get(tbl)
                                    if parent is not None:
                                        try:
                                            parent.remove(tbl)
                                        except ValueError:
                                            pass
                            # Ensure every remaining cell has at
                            # least one w:p (Word requirement).
                            for tc in root.iter(TC_TAG):
                                if tc.find(P_TAG) is None:
                                    tc.append(ET.Element(P_TAG))

                            if removed:
                                data = ET.tostring(
                                    root,
                                    xml_declaration=True,
                                    encoding="UTF-8",
                                    short_empty_elements=True,
                                )
                                logger.info(
                                    "Stripped %d inline cert paragraph(s) from authored body (recursive)",
                                    removed,
                                )
                                modified = True
                        except Exception as e:
                            logger.warning(
                                "Inline-cert strip failed: %s", e
                            )
                    zout.writestr(item, data)

        return out_buf.getvalue() if modified else docx_bytes
    except Exception:
        logger.exception("Inline-cert strip failed — returning original")
        return docx_bytes


def _strip_html_and_bracket_artifacts(docx_bytes: bytes) -> bytes:
    """Strip literal HTML tags and bracketed image placeholders that
    Claude sometimes emits as text inside the body.

    User reports a recurring class of bug where Claude's authored
    DOCX contains text like
        '<p style="text-align: center;">AUSTRIAN EMBASSY<br>LONDON</p>'
    rendered as visible text, plus '[Coat of Arms]', '[Stamp: ...]',
    '[Signature: ...]'. The bracketed markers violate the TEXT-ONLY
    rule in the prompt; the HTML tags happen when Claude
    misinterprets "center the masthead" in HTML terms instead of
    using python-docx alignment.

    Strategy:
      * Walk every paragraph (including those inside tables).
      * Concatenate text from ALL <w:t> elements across runs into
        one string — Claude often splits a single tag across
        runs (p.add_run("<p>") + p.add_run("text") + p.add_run("</p>")),
        so per-<w:t> scanning misses them.
      * Strip HTML tags via regex (keeping inner text).
      * Drop bracketed image markers entirely.
      * Write cleaned text back into the FIRST run; blank the rest.
      * If the paragraph ends up empty, drop the whole paragraph
        in pass 2.

    Best-effort; failures return the original bytes unchanged.
    """
    try:
        import io as _io
        import re as _re2
        import zipfile as _zip
        from xml.etree import ElementTree as ET

        W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        XML_NS = "http://www.w3.org/XML/1998/namespace"
        ET.register_namespace("w", W_NS)
        P_TAG = "{%s}p" % W_NS
        R_TAG = "{%s}r" % W_NS
        T_TAG = "{%s}t" % W_NS

        TAG_RE = _re2.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9]*\b[^>]*>")
        BRACKET_RE = _re2.compile(
            r"\[\s*(?:Coat of Arms|Stamp(?:\s*:\s*[^\]]+)?|Signature"
            r"(?:\s*:\s*[^\]]+)?|Photo|Seal|Logo|QR\s*Code|Barcode|"
            r"Crest)\s*\]",
            _re2.I,
        )
        SUSPECT = ("<", ">", "[")

        in_buf = _io.BytesIO(docx_bytes)
        out_buf = _io.BytesIO()
        modified = False
        paras_cleaned = 0
        chars_removed = 0
        empty_paras_removed = 0

        with _zip.ZipFile(in_buf, "r") as zin:
            with _zip.ZipFile(out_buf, "w", _zip.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "word/document.xml":
                        try:
                            root = ET.fromstring(data)
                            body = root.find("{%s}body" % W_NS)
                            if body is not None:
                                # Pass 1 \u2014 paragraph-level strip.
                                for p in root.iter(P_TAG):
                                    runs = list(p.findall(R_TAG))
                                    if not runs:
                                        continue
                                    full = "".join(
                                        (t.text or "")
                                        for r in runs
                                        for t in r.findall(T_TAG)
                                    )
                                    if not full or not any(c in full for c in SUSPECT):
                                        continue
                                    cleaned = full
                                    if "<" in cleaned and ">" in cleaned:
                                        cleaned = TAG_RE.sub(" ", cleaned)
                                    if "[" in cleaned:
                                        cleaned = BRACKET_RE.sub("", cleaned)
                                    # Drop unterminated openers/dangling closers.
                                    if "<" in cleaned or ">" in cleaned:
                                        cleaned = _re2.sub(
                                            r"<\s*/?\s*[a-zA-Z][^<>]*$",
                                            "",
                                            cleaned,
                                        )
                                        cleaned = _re2.sub(
                                            r"^[^<>]*?>",
                                            "",
                                            cleaned,
                                        )
                                    cleaned = _re2.sub(
                                        r"[ \t]{2,}", " ", cleaned
                                    ).strip()
                                    if cleaned == full:
                                        continue
                                    chars_removed += len(full) - len(cleaned)
                                    paras_cleaned += 1
                                    modified = True
                                    if not cleaned:
                                        for r in runs:
                                            for t in r.findall(T_TAG):
                                                t.text = ""
                                        continue
                                    first_run = runs[0]
                                    first_t = first_run.find(T_TAG)
                                    if first_t is None:
                                        first_t = ET.SubElement(
                                            first_run, T_TAG
                                        )
                                    first_t.text = cleaned
                                    first_t.set(
                                        "{%s}space" % XML_NS, "preserve"
                                    )
                                    for r in runs[1:]:
                                        for t in r.findall(T_TAG):
                                            t.text = ""

                                # Pass 2 \u2014 drop now-empty paragraphs.
                                parent_map = {
                                    c: p2 for p2 in body.iter() for c in p2
                                }
                                for p in list(body.iter(P_TAG)):
                                    has_text = any(
                                        (t.text or "").strip()
                                        for t in p.iter(T_TAG)
                                    )
                                    has_drawing = any(
                                        True for _ in p.iter("{%s}drawing" % W_NS)
                                    )
                                    has_pb = any(
                                        b.get("{%s}type" % W_NS) == "page"
                                        for b in p.iter("{%s}br" % W_NS)
                                    )
                                    has_sectpr = (
                                        p.find("{%s}pPr/{%s}sectPr"
                                               % (W_NS, W_NS)) is not None
                                    )
                                    if not (has_text or has_drawing or has_pb or has_sectpr):
                                        parent = parent_map.get(p)
                                        if parent is not None:
                                            try:
                                                parent.remove(p)
                                                empty_paras_removed += 1
                                            except Exception:
                                                pass

                                if modified:
                                    data = ET.tostring(
                                        root,
                                        xml_declaration=True,
                                        encoding="UTF-8",
                                        standalone=True,
                                    )
                        except Exception:
                            logger.exception(
                                "strip_html_and_bracket_artifacts: "
                                "failed to parse document.xml \u2014 "
                                "leaving untouched"
                            )
                    zout.writestr(item, data)

        if modified:
            logger.info(
                "strip_html_and_bracket_artifacts: cleaned %d paras "
                "(removed %d chars), dropped %d empty paras",
                paras_cleaned,
                chars_removed,
                empty_paras_removed,
            )
            return out_buf.getvalue()
        return docx_bytes
    except Exception:
        logger.exception(
            "strip_html_and_bracket_artifacts crashed; "
            "returning bytes unchanged"
        )
        return docx_bytes


def _merge_adjacent_compatible_tables(docx_bytes: bytes) -> bytes:
    """Merge runs of consecutive single-row <w:tbl> elements that
    have the same column count into one multi-row table.

    Claude sometimes fragments tax-form sections into N one-row
    tables (one per RN/RA entry) instead of one table with N rows.
    This walks the body, finds adjacent <w:tbl> siblings whose
    column count matches, and consolidates by moving rows from the
    trailing tables into the first one, then deleting the consumed
    tables. Empty paragraphs between compatible tables are also
    removed.

    Best-effort; failures return the original bytes unchanged.
    """
    try:
        import io as _io2
        import zipfile as _zip
        from xml.etree import ElementTree as ET

        W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ET.register_namespace("w", W_NS)
        TBL = "{%s}tbl" % W_NS
        TR = "{%s}tr" % W_NS
        TC = "{%s}tc" % W_NS
        TBLGRID = "{%s}tblGrid" % W_NS

        def _col_count(tbl_el):
            grid = tbl_el.find(TBLGRID)
            if grid is not None:
                return len(list(grid))
            best = 0
            for tr in tbl_el.findall(TR):
                n = len(tr.findall(TC))
                if n > best:
                    best = n
            return best

        in_buf = _io2.BytesIO(docx_bytes)
        out_buf = _io2.BytesIO()
        modified = False
        merges_done = 0

        with _zip.ZipFile(in_buf, "r") as zin:
            with _zip.ZipFile(out_buf, "w", _zip.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "word/document.xml":
                        try:
                            root = ET.fromstring(data)
                            body = root.find("{%s}body" % W_NS)
                            if body is not None:
                                children = list(body)
                                i = 0
                                while i < len(children):
                                    el = children[i]
                                    if el.tag != TBL:
                                        i += 1
                                        continue
                                    head_cols = _col_count(el)
                                    if head_cols == 0:
                                        i += 1
                                        continue
                                    # Try to absorb next tables.
                                    while True:
                                        # Find next non-empty
                                        # sibling.
                                        j = i + 1
                                        skipped = []
                                        while j < len(children):
                                            nxt = children[j]
                                            if nxt.tag == TBL:
                                                break
                                            tag = nxt.tag.split("}")[-1]
                                            if tag in ("p", "sectPr"):
                                                if tag == "p":
                                                    has_text = False
                                                    for t in nxt.iter("{%s}t" % W_NS):
                                                        if (t.text or "").strip():
                                                            has_text = True
                                                            break
                                                    if has_text:
                                                        break
                                                skipped.append(j)
                                                j += 1
                                                continue
                                            break
                                        if (
                                            j >= len(children)
                                            or children[j].tag != TBL
                                        ):
                                            break
                                        nxt = children[j]
                                        if _col_count(nxt) != head_cols:
                                            break
                                        # Move rows.
                                        for tr in list(nxt.findall(TR)):
                                            el.append(tr)
                                        # Delete absorbed table +
                                        # any blank paragraphs.
                                        for idx in sorted(
                                            skipped + [j], reverse=True
                                        ):
                                            try:
                                                body.remove(children[idx])
                                            except Exception:
                                                pass
                                        children = list(body)
                                        modified = True
                                        merges_done += 1
                                    i += 1

                                if modified:
                                    data = ET.tostring(
                                        root,
                                        xml_declaration=True,
                                        encoding="UTF-8",
                                        standalone=True,
                                    )
                        except Exception:
                            logger.exception(
                                "merge_adjacent_compatible_tables: "
                                "failed to parse document.xml -- "
                                "leaving untouched"
                            )
                    zout.writestr(item, data)

        if modified:
            logger.info(
                "merge_adjacent_compatible_tables: consolidated "
                "%d adjacent compatible table(s)", merges_done,
            )
            return out_buf.getvalue()
        return docx_bytes
    except Exception:
        logger.exception(
            "merge_adjacent_compatible_tables crashed; "
            "returning bytes unchanged"
        )
        return docx_bytes


def _strip_broken_image_drawings(docx_bytes: bytes) -> bytes:
    """Remove any <w:drawing> whose embedded relationship ID
    doesn't actually exist in word/_rels/document.xml.rels.

    Claude's scripts sometimes call doc.add_picture(path) where
    `path` resolves but the file is removed before .save() runs, OR
    they reference an inline image rel that doesn't make it into
    the saved package. The user sees "The picture can't be
    displayed" in Word for each orphan drawing. Strip them.

    Failures are non-fatal — returns original bytes on error.
    """
    try:
        import io
        import re as _re
        import zipfile
        from xml.etree import ElementTree as ET

        W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
        ET.register_namespace("w", W_NS)
        ET.register_namespace("r", R_NS)
        ET.register_namespace("", REL_NS)

        in_buf = io.BytesIO(docx_bytes)
        out_buf = io.BytesIO()

        # Pre-read all members.
        with zipfile.ZipFile(in_buf, "r") as zin:
            members = {item.filename: zin.read(item.filename) for item in zin.infolist()}

        rels_data = members.get("word/_rels/document.xml.rels", b"")
        doc_data = members.get("word/document.xml", b"")
        if not rels_data or not doc_data:
            return docx_bytes

        # Collect the set of valid rIds (any relationship pointing at
        # an image — and crucially, an image whose target exists in
        # the zip).
        valid_rids = set()
        try:
            rels_root = ET.fromstring(rels_data)
            for r in rels_root:
                rid = r.get("Id")
                rtype = r.get("Type") or ""
                target = r.get("Target") or ""
                if "image" not in rtype.lower():
                    continue
                # Resolve target relative to word/
                tpath = target
                if tpath.startswith("/"):
                    tpath = tpath[1:]
                if tpath.startswith("../"):
                    tpath = tpath[3:]
                else:
                    tpath = "word/" + tpath
                if tpath in members:
                    valid_rids.add(rid)
        except Exception as e:
            logger.warning("rels parse failed: %s", e)
            return docx_bytes

        # Walk document.xml drawings, remove ones whose r:embed isn't
        # in valid_rids.
        try:
            doc_root = ET.fromstring(doc_data)
        except Exception:
            return docx_bytes

        body = doc_root.find("{%s}body" % W_NS)
        if body is None:
            return docx_bytes

        removed = 0
        DRAWING_TAG = "{%s}drawing" % W_NS
        EMBED_ATTR = "{%s}embed" % R_NS

        # Build a parent map.
        parent_map = {c: p for p in doc_root.iter() for c in p}

        for drawing in list(doc_root.iter(DRAWING_TAG)):
            # Find r:embed attribute anywhere inside this drawing.
            embed_rid = None
            for el in drawing.iter():
                rid = el.get(EMBED_ATTR)
                if rid:
                    embed_rid = rid
                    break
            if embed_rid is None or embed_rid in valid_rids:
                continue
            # Orphan drawing — remove from its parent.
            parent = parent_map.get(drawing)
            if parent is not None:
                parent.remove(drawing)
                removed += 1

        if removed:
            new_doc = ET.tostring(
                doc_root, xml_declaration=True, encoding="UTF-8",
                short_empty_elements=True,
            )
            members["word/document.xml"] = new_doc
            with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for name, data in members.items():
                    zout.writestr(name, data)
            logger.info(
                "Removed %d broken-image drawing(s) (orphaned rIds)", removed
            )
            return out_buf.getvalue()
        return docx_bytes
    except Exception:
        logger.exception("Broken-drawing cleanup failed — returning original")
        return docx_bytes


def author_rebuild_docx(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    *,
    model: Optional[str] = None,
    timeout_seconds: int = 300,
) -> bytes:
    """End-to-end Claude-authored rebuild.

    Sends the PDF to Claude, gets back a python-docx script, executes
    it in a sandboxed subprocess, and returns the rebuilt DOCX bytes.

    Raises RuntimeError or ValueError if any step fails — the caller
    should fall back to the segment-driven pipeline.
    """
    # Multi-turn mode: when REBUILD_MULTITURN is enabled (default
    # on), delegate to the tool-use loop in
    # claude_multiturn_rebuild — that's the "match claude.ai chat"
    # path where Claude sees its own output and iterates until it
    # matches the source. Falls back to single-shot on any failure.
    use_multiturn = (
        os.getenv("REBUILD_MULTITURN", "1").strip().lower()
        not in ("", "0", "false", "no", "off")
    )
    if use_multiturn:
        try:
            from app.services.claude_multiturn_rebuild import (
                author_rebuild_docx_multiturn,
            )
            logger.info(
                "Using multi-turn rebuild loop (model=%s)",
                model or "claude-opus-4-6",
            )
            return author_rebuild_docx_multiturn(
                pdf_bytes,
                source_lang,
                target_lang,
                model=model or "claude-opus-4-6",
            )
        except Exception:
            logger.exception(
                "Multi-turn rebuild failed — falling back to single-shot"
            )

    # Use a stable, sandbox-readable path.
    out_dir = Path(tempfile.mkdtemp(prefix="claude_authored_out_"))
    output_path = str(out_dir / "rebuild.docx")

    # Extract embedded images so Claude can re-use the real logo /
    # stamp / signature bitmaps instead of bracketed placeholders.
    images = _extract_pdf_images(pdf_bytes, out_dir)

    # Vision pre-pass: extract every data table as structured JSON
    # so the author script can paste cell values verbatim instead of
    # re-OCR'ing the table from the PDF image (which causes the
    # crammed-cells regression).
    try:
        tables = _extract_tables_via_vision(pdf_bytes)
    except Exception:
        logger.exception("Vision table pre-pass failed — continuing without")
        tables = []

    try:
        raw = _call_claude_to_author(
            pdf_bytes=pdf_bytes,
            source_lang=source_lang,
            target_lang=target_lang,
            output_path=output_path,
            images=images,
            tables=tables,
            model=model or "claude-opus-4-6",
        )
        script = _strip_code_fence(raw)
        _validate_script(script, output_path)
        docx_bytes = _run_script_in_sandbox(
            script,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
        )
        # Safety net: strip any vertical-text / rotation that Claude
        # may have emitted despite the explicit prompt rule.
        docx_bytes = _strip_rotation_from_docx(docx_bytes)
        docx_bytes = _strip_layout_table_borders(docx_bytes)
        docx_bytes = _split_crammed_table_rows(docx_bytes)
        # Strip any "CERTIFIED TRANSLATION" affidavit block Claude
        # left inside the body — the wrapper appends the real cert
        # AFTER the body, so an inline cert is always a duplicate.
        docx_bytes = _strip_inline_cert_blocks(docx_bytes)
        # Strip literal HTML tags and bracketed image placeholders
        # (e.g. '<p style="text-align: center;">FOO</p>' or
        # '[Coat of Arms]') Claude sometimes leaves in body text
        # despite the prompt forbidding both.
        docx_bytes = _strip_html_and_bracket_artifacts(docx_bytes)
        # Consolidate adjacent 1-row tables into one multi-row
        # table -- fixes the "29 separate one-row tables for
        # RN1..RN29" fragmentation pattern.
        docx_bytes = _merge_adjacent_compatible_tables(docx_bytes)
        # If Claude left any bracketed image placeholders despite
        # the prompt instruction, try to substitute the actual
        # extracted image. Uses out_dir/images/.
        docx_bytes = _replace_image_placeholders(docx_bytes, out_dir)
        # Final cleanup: remove any <w:drawing> whose embedded rId
        # doesn't actually exist in the rels file. This is what
        # produces the "The picture can't be displayed" red-X in
        # Word — gone now.
        docx_bytes = _strip_broken_image_drawings(docx_bytes)
        logger.info(
            "Authored rebuild OK (%d bytes)", len(docx_bytes)
        )
        return docx_bytes
    finally:
        # Wipe the output dir — the bytes are already in memory.
        try:
            shutil.rmtree(out_dir, ignore_errors=True)
        except Exception:
            pass
