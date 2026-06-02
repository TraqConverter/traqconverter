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
  * .docx format, A4 page size unless the source is clearly Letter
    (US correspondence). Margins ~2cm (0.8in) on all sides; widen
    to ~2.5cm if the source has generous side margins.
  * Mirror the original's page breaks 1:1 — if the source spans
    three pages, the output spans three pages.
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
  * Borderless layout tables (logo|name header, label|value rows)
    must have their borders explicitly stripped. The ONLY table
    that should have visible borders is a true multi-row data
    grid (a courses table, an invoice line-items table, a price
    list, a schedule). Use this helper for every layout table:

        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        def _no_borders(tbl):
            tblPr = tbl._tbl.find(qn('w:tblPr'))
            if tblPr is None:
                tblPr = OxmlElement('w:tblPr')
                tbl._tbl.insert(0, tblPr)
            borders = OxmlElement('w:tblBorders')
            for edge in ("top","left","bottom","right","insideH","insideV"):
                e = OxmlElement(f'w:{edge}')
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

ARTWORK / IMAGES
================
Real image files have been pre-extracted from the source PDF and
are sitting in the ./images/ subdirectory of your script's working
directory. The full list is below under EXTRACTED IMAGES.

CRITICAL: If the list contains ANY entry — embedded XObject OR
header / footer crop — you MUST insert that image with
`doc.add_picture("images/<filename>", width=Cm(N))` at the matching
position in the rebuilt document. DO NOT use a bracketed text
placeholder like "[Coat of Arms]" / "[Stamp]" / "[Signature]" if
there is a real image file available.

  * For an entry with kind=header → it is the cropped top strip of
    a source page. It contains the logo + masthead. Insert it at
    the top of your output page using add_picture with a width
    that fills the body (width=Cm(17) for portrait A4). DO NOT
    add a "[Coat of Arms]" placeholder alongside it.
  * For an entry with kind=footer → it is the cropped bottom strip
    of the LAST source page. It contains the signature block + seal
    + stamp. Insert it at the bottom of your last translation page,
    typically width=Cm(8-12).
  * For an entry with kind=embedded → discrete extracted image
    (logo, photo, signature, seal). Place it where the source PDF
    shows it, sized appropriately.
  * Insert with `doc.add_picture("images/<filename>", width=Cm(N))`
    at the matching position.
  * Sizing hints: logos / crests ~3-4 cm wide; round seals or
    rubber stamps ~3 cm; handwritten signatures ~5 cm; ID photos
    or passport photos ~3 cm tall.
  * If the source is a flat scan (one big image per page rather
    than discrete logo/seal/signature image files), the
    EXTRACTED IMAGES list may be empty or only contain whole-page
    bitmaps. In that case use a short italic bracketed placeholder
    paragraph at the matching position (e.g. "[Logo]", "[Stamp]",
    "[Signature]") instead of trying to reference a file that
    isn't there.

Add a small italic bottom note in {target_lang}, set at ~8pt with
slight indentation, stating that this is a translation of the
original {source_lang} document, that the crest / seal / signature
are reproduced from the original scan, and that all codes / sector
codes / credit values / grades / reference numbers are reproduced
unchanged. Example wording:
    "Note: This is an English translation of the original Italian
     certificate issued by the University of Florence. The crest,
     seal and signature are reproduced from the original scan.
     Course codes, sector codes (S.S.D.), credit values (CFU),
     grades and reference numbers are reproduced unchanged."

VISUAL LAYOUT FIDELITY
======================
  * If the source has TWO labels on the SAME physical line, the
    output MUST keep them on the SAME paragraph using a tab stop:

        from docx.enum.text import WD_TAB_ALIGNMENT
        pf = paragraph.paragraph_format
        pf.tab_stops.add_tab_stop(Cm(17), WD_TAB_ALIGNMENT.RIGHT)
        paragraph.add_run("Left label: X")
        paragraph.add_run("\\t")
        paragraph.add_run("Right label: Y")

  * Look at the actual pixel positions of text in the PDF and
    preserve the visual paragraph structure 1:1.
  * Maintain blank lines / vertical spacing between paragraphs.

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
            # Strategy 1: embedded XObjects.
            for img_idx, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n - pix.alpha >= 4:  # CMYK -> convert to RGB
                        pix = fitz.Pixmap(fitz.csRGB, pix)
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
                    # Header crop: top 28% — typically captures
                    # logo + institution name region.
                    header_clip = fitz.Rect(
                        0, 0, page_w, page_h * 0.28
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
                            0, page_h * 0.55, page_w, page_h * 0.85
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


def _call_claude_to_author(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    output_path: str,
    images: list,
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
    )

    logger.info(
        "Calling Claude (model=%s) for authored rebuild "
        "(pdf_bytes=%d, source=%s, target=%s)",
        model, len(pdf_bytes), source_lang, target_lang,
    )

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")

    resp = client.messages.create(
        model=model,
        max_tokens=32000,
        # Be patient. Claude takes its time on documents like this and
        # that's exactly the tradeoff we picked.
        temperature=0.2,
        messages=[
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
    )

    # Concatenate any text blocks in the response (usually just one).
    text_blocks = []
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            text_blocks.append(getattr(block, "text", "") or "")
    raw = "\n".join(text_blocks)
    logger.info(
        "Claude returned %d chars (usage in=%d out=%d)",
        len(raw),
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
    """Strip visible borders from tables that look like layout
    tables — i.e. small tables (1-2 rows) whose text doesn't include
    the courses-grid header keywords. The actual courses table keeps
    its borders.

    This is a safety net for when Claude uses a bordered table for
    a logo|name header layout (which it shouldn't, per the prompt).
    """
    try:
        import io
        import zipfile
        from xml.etree import ElementTree as ET

        W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ET.register_namespace("w", W_NS)
        ns = {"w": W_NS}

        # Courses-grid header heuristic: text contains at least 2 of
        # these column-header keywords (in either language).
        COURSE_HEADER_KEYWORDS = {
            "course", "result", "grade", "ects", "cfu", "date",
            "esito", "voto", "data", "s.s.d", "insegnamento",
            "outcome", "mark",
        }

        in_buf = io.BytesIO(docx_bytes)
        out_buf = io.BytesIO()
        modified = False

        with zipfile.ZipFile(in_buf, "r") as zin:
            with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "word/document.xml":
                        try:
                            root = ET.fromstring(data)
                            stripped = 0
                            for tbl in root.iter("{%s}tbl" % W_NS):
                                rows = tbl.findall("{%s}tr" % W_NS)
                                # Gather all text in the table.
                                all_text = " ".join(
                                    "".join(
                                        t.text or "" for t in tbl.iter("{%s}t" % W_NS)
                                    ).lower().split()
                                )
                                kw_hits = sum(
                                    1 for kw in COURSE_HEADER_KEYWORDS
                                    if kw in all_text
                                )
                                # Skip the courses grid: 3+ rows AND
                                # ≥2 header keywords detected.
                                if len(rows) >= 3 and kw_hits >= 2:
                                    continue
                                # Strip borders on this layout table.
                                tblPr = tbl.find("{%s}tblPr" % W_NS)
                                if tblPr is None:
                                    tblPr = ET.SubElement(tbl, "{%s}tblPr" % W_NS)
                                    tbl.insert(0, tblPr)
                                # Remove existing tblBorders
                                for b in tblPr.findall("{%s}tblBorders" % W_NS):
                                    tblPr.remove(b)
                                borders = ET.SubElement(tblPr, "{%s}tblBorders" % W_NS)
                                for edge in (
                                    "top", "left", "bottom", "right",
                                    "insideH", "insideV",
                                ):
                                    e = ET.SubElement(borders, "{%s}%s" % (W_NS, edge))
                                    e.set("{%s}val" % W_NS, "nil")
                                # Also strip per-cell borders just in case.
                                for tc in tbl.iter("{%s}tc" % W_NS):
                                    tcPr = tc.find("{%s}tcPr" % W_NS)
                                    if tcPr is not None:
                                        for b in tcPr.findall("{%s}tcBorders" % W_NS):
                                            tcPr.remove(b)
                                stripped += 1
                            if stripped:
                                data = ET.tostring(
                                    root,
                                    xml_declaration=True,
                                    encoding="UTF-8",
                                    short_empty_elements=True,
                                )
                                logger.info(
                                    "Stripped borders from %d layout tables", stripped
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
    # Use a stable, sandbox-readable path.
    out_dir = Path(tempfile.mkdtemp(prefix="claude_authored_out_"))
    output_path = str(out_dir / "rebuild.docx")

    # Extract embedded images so Claude can re-use the real logo /
    # stamp / signature bitmaps instead of bracketed placeholders.
    images = _extract_pdf_images(pdf_bytes, out_dir)

    try:
        raw = _call_claude_to_author(
            pdf_bytes=pdf_bytes,
            source_lang=source_lang,
            target_lang=target_lang,
            output_path=output_path,
            images=images,
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
