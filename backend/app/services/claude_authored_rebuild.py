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
You are translating and rebuilding an official document. Your job:
read the attached PDF carefully, translate every visible textual
element from {source_lang} to {target_lang}, and produce a Microsoft
Word .docx file that visually mirrors the original layout as closely
as possible.

OUTPUT FORMAT
=============
Return a single, complete, runnable Python 3 script wrapped in a
```python ``` code block. No prose, no preamble, no postscript — just
the code block.

The script MUST:
  * Use only `python-docx` (already installed) and the Python
    standard library. No other third-party packages.
  * Import: `from docx import Document` and `from docx.shared
    import Pt, Cm, Inches, RGBColor` and
    `from docx.enum.text import WD_ALIGN_PARAGRAPH` and
    `from docx.enum.table import WD_ALIGN_VERTICAL` as needed.
  * Build the DOCX in memory then save it to EXACTLY this path:
      OUTPUT_PATH = r"{output_path}"
      doc.save(OUTPUT_PATH)
  * NOT touch the filesystem anywhere else.
  * NOT call subprocess, os.system, requests, urllib, socket, or any
    network module.
  * NOT print() anything — silent execution.

LAYOUT FIDELITY RULES
=====================
  * Translate ALL visible text. Do not transliterate or leave any
    {source_lang} phrasing in the output.
  * Preserve identifiers, codes, dates, signatures, file/registration
    numbers, and proper names verbatim.
  * Recreate tables as Word tables (doc.add_table) with the same
    number of rows and columns as the original. Set borders on table
    cells that have visible borders in the source.
  * Preserve alignment (centered titles, justified body paragraphs,
    right-aligned numbers).
  * Preserve relative font emphasis: bold for headings/labels,
    italic for placeholder hints, larger sizes for titles.
  * For headers and logos that appear as images in the source, use a
    bracketed placeholder paragraph or table cell (e.g. "[Coat of
    Arms]", "[Stamp]", "[Signature]") — never reference image files.
  * For multi-page documents, use page breaks
    (`paragraph.add_run().add_break(WD_BREAK.PAGE)`) between pages so
    section structure is preserved.
  * Match page orientation to the source PDF. Default to A4 portrait
    unless the source is landscape.
  * Set margins to 2.0 cm on all sides unless the source clearly
    uses different margins.

QUALITY BAR
===========
Imagine a certified translator will sign off on this document. Every
table cell must align with the original. Every footnote, asterisk,
parenthetical, and decoding key must appear in the translation. If
the original has a courses table with 7 columns, the output has a
courses table with 7 columns — not paragraphs.

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
    _BLOCKED = (
        "socket", "ssl", "ftplib", "telnetlib",
        "smtplib", "poplib", "imaplib", "http",
        "http.client", "urllib", "urllib.request",
        "urllib.parse", "requests", "httpx",
        "subprocess", "multiprocessing", "asyncio.subprocess",
        "ctypes", "ctypes.util", "win32api", "win32com",
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


def _call_claude_to_author(
    pdf_bytes: bytes,
    source_lang: str,
    target_lang: str,
    output_path: str,
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
    try:
        script_path = work_dir / "rebuild.py"
        # Write the preamble + user code.
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(_SANDBOX_PREAMBLE)
            f.write(script)
            f.write("\n")

        cmd = [sys.executable, "-I", "-S", str(script_path)]
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

    try:
        raw = _call_claude_to_author(
            pdf_bytes=pdf_bytes,
            source_lang=source_lang,
            target_lang=target_lang,
            output_path=output_path,
            model=model or "claude-sonnet-4-5-20250929",
        )
        script = _strip_code_fence(raw)
        _validate_script(script, output_path)
        docx_bytes = _run_script_in_sandbox(
            script,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
        )
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
