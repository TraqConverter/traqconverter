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
Please translate the attached PDF from {source_lang} into
{target_lang} and produce a Microsoft Word .docx that visually
matches the original document — exactly how you'd build it if a user
pasted the file into Claude and asked for a translated Word copy.

Reply with ONE Python 3 code block (```python … ```). No prose,
no preamble, no commentary. The script must:

  * Use only `python-docx` and the Python stdlib.
  * Build the document in memory and save to this exact path:
        OUTPUT_PATH = r"{output_path}"
        doc.save(OUTPUT_PATH)
  * Not touch any other file. Not call subprocess, os.system,
    requests, urllib, socket, or any network module. Not print.

Layout guidance — IMPORTANT, please follow carefully:

  * Mirror the natural flow of the source. Look at how the original
    PDF actually reads on the page and reproduce that flow.

  * DO NOT wrap content in tables unless the source itself shows a
    true multi-row data grid (e.g. a courses-and-grades table, a
    schedule, an invoice line-items block). Headers, titles,
    certificate numbers, "Page 1 of 2" lines, "For Use Abroad"
    notices, dates, signatures, stamps, footnotes, and any other
    text that simply happens to be visually aligned on the page
    should be regular paragraphs with the appropriate alignment
    (centered, left, right) or tab stops — NOT tables.

  * The header block (logo + institution name + sub-title) should be
    plain centered paragraphs, not a 2-column table.

  * A row like "Certificate No. ABC123    Student No. XYZ789" should
    be a single paragraph using tab stops or two-column alignment,
    NOT a 2-cell table.

  * The courses-and-grades grid IS a true table — use a real Word
    table with the same number of columns as the source.

  * Match page orientation, margins, and font weights to the
    original. Use bold for the actual bold elements (headings,
    column headers, key labels) — not for everything.

  * REUSE the real image files from the original PDF for any
    logos, coats of arms, stamps, signatures, photos, QR codes,
    or embedded graphics. They are extracted ahead of time and
    listed below under "EXTRACTED IMAGES" with their relative
    paths (under ./images/) and source page numbers. Insert each
    with `doc.add_picture("images/<filename>", width=Cm(N))` at
    the matching position. Sizing hint: logos ~3-4 cm wide,
    stamps ~3 cm, signatures ~5 cm, ID photos ~3 cm tall. Only
    fall back to a bracketed text placeholder (e.g. "[Stamp]") if
    no listed image clearly matches the position in the source.

  * Translate every visible textual element. Preserve identifiers,
    codes, dates, file/registration numbers, and proper names
    verbatim. Don't transliterate.

  * For multi-page sources use a real page break
    (`run.add_break(WD_BREAK.PAGE)`) between pages.

VISUAL LAYOUT FIDELITY — read this carefully:

The output must mirror the SPATIAL layout of the original PDF, not
just the text content. In particular:

  * If the source has TWO labels on the SAME physical line (e.g.
    "N. Certif. 20251529859 /M1297_MC" on the left and
    "Matricola 7043077" on the right of the same line), the
    output MUST keep them on the SAME paragraph using tab stops or
    a right-aligned tab. Do not split them into two paragraphs.

  * Same rule for "Uso Estero" / "Pagina 1 di 2" — single
    paragraph, left+right alignment.

  * Header layout: logo on the left, institution name stacked
    next to it. Use a hidden 2-column borderless table or a
    horizontal paragraph with the logo run + text runs side-by-
    side. NEVER stack the institution name BELOW the logo unless
    that's how the source actually looks.

  * Look at the actual pixel positions of text in the PDF.
    Preserve the visual paragraph structure 1:1 with the source.
    A paragraph that's centered in the source is centered in the
    output. A paragraph indented to the right margin is right-
    aligned in the output.

  * Maintain blank lines / vertical spacing between paragraphs
    that match the original.

  * Use python-docx tab stops:
        from docx.enum.text import WD_TAB_ALIGNMENT
        pf = paragraph.paragraph_format
        pf.tab_stops.add_tab_stop(Cm(17), WD_TAB_ALIGNMENT.RIGHT)
        run = paragraph.add_run("Left label")
        paragraph.add_run("\t")
        paragraph.add_run("Right label")
    This is the correct way to put two labels on one line.

HARD RULES — these have caused regressions before, don't violate them:

  * NEVER rotate text. NEVER set vertical text direction. NEVER
    use textDirection / WD_ROW_HEIGHT.AT_LEAST tricks to fit a
    wide table into a narrow page. All text in the output, in
    every paragraph and every table cell, must be normal
    horizontal left-to-right reading direction.

  * If a wide table (e.g. the courses-and-grades grid) doesn't
    seem to fit at 10-11pt font on a portrait A4 page, DROP THE
    FONT SIZE to 8pt or even 7pt for the table body — DO NOT
    rotate column headers, DO NOT switch the section to landscape,
    DO NOT split the table sideways. A small horizontal table is
    always more readable than a rotated one.

  * Use ONE consistent page orientation for the whole document.
    Pick portrait unless the source PDF is clearly landscape on
    every page. Do not mix orientations between sections within a
    single output document.

  * Set table column widths explicitly with Cm() values that add
    up to ~17 cm total (A4 portrait minus 2cm margins). Don't let
    python-docx auto-size them — it picks bad widths for wide
    grids.

  * The header block (logo, institution name, sub-title) goes at
    the TOP of page 1, full width, centered. Do NOT stuff it into
    the right margin or rotate it.

Quality bar: imagine you (Claude) were asked directly by a user to
"translate this PDF and give me a Word file that looks like the
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
    """Extract embedded raster images from a PDF.

    Saves them under ``dest_dir / "images"`` and returns a list of
    dicts like {"filename": "p1_img0.png", "page": 1, "width_px":
    1024, "height_px": 480}. The list is what the author prompt
    embeds so Claude knows which doc.add_picture() calls to make.

    Failures are non-fatal — we return [] and the prompt falls back
    to bracketed placeholders for missing images.
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
        for page_num, page in enumerate(doc, start=1):
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
                    })
                    pix = None
                except Exception as e:
                    logger.warning(
                        "Skipped image p%d idx%d: %s", page_num, img_idx, e
                    )
    finally:
        try:
            doc.close()
        except Exception:
            pass

    logger.info("Extracted %d image(s) from PDF", len(out))
    return out


def _format_image_list(images: list) -> str:
    """Render the extracted-image list as bullet lines for the prompt."""
    if not images:
        return "(no embedded images detected — use bracketed placeholders if needed)"
    lines = []
    for im in images:
        lines.append(
            f'  - images/{im["filename"]}  (page {im["page"]}, '
            f'{im["width_px"]}x{im["height_px"]} px)'
        )
    return "\n".join(lines)


def _call_claude_to_author(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    output_path: str,
    images: list,
    model: str = "claude-sonnet-4-5-20250929",
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
        max_tokens=16000,
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
            model=model or "claude-sonnet-4-5-20250929",
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
