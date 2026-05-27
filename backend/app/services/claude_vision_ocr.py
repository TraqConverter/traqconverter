"""Claude Vision OCR for image documents.

Why this exists
---------------
pytesseract handles plain text scans reasonably well but is poor on
ID/passport documents because of:
  * stylised security fonts
  * holographic / watermark backgrounds
  * curved or rotated micro-text
  * low contrast areas next to photographs

Claude Vision reads all of the above cleanly. This module wraps a
single Anthropic call that takes an image and returns a list of
(text, bbox) tuples in the source image's pixel coordinates — the
same shape `_extract_image` was producing from tesseract, so the
caller can swap one for the other transparently.

Only runs when ANTHROPIC_API_KEY is set. If anything goes wrong
(missing package, network, bad JSON), the caller falls back to
tesseract.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


# Prompt revision marker — bump when you change the prompt so the
# worker log can confirm a code reload happened.
_PROMPT_VERSION = "v7-no-logo-hallucination"


_SYSTEM_PROMPT = """You are a certified-translator's pre-press tool. \
Given an image of a document, produce a STRUCTURED TRANSCRIPTION that \
will be used to render a clean replica of the document. Output strict \
JSON only.

Output shape:
  {
    "width": <int px>,
    "height": <int px>,
    "document_font_family": "serif" | "sans_serif" | "monospace",
    "elements": [
      {
        "text": "<exact text OR placeholder label>",
        "bbox": [x0, y0, x1, y1],
        "kind": "text" | "placeholder",
        "placeholder_kind": null | "coat_of_arms" | "logo" | "photo" |
                            "stamp" | "signature" | "barcode" | "qr" |
                            "illegible" | "handwritten" | "blanked_out",
        "alignment": "left" | "center" | "right",
        "bold": true | false,
        "italic": true | false,
        "all_caps": true | false,
        "size": "small" | "normal" | "large" | "xlarge",
        "font_family": "serif" | "sans_serif" | "monospace"
      },
      ...
    ]
  }

============================================================
SEGMENTATION — THE CRITICAL RULE
============================================================
Group text into LOGICAL READING UNITS, not visual lines. A logical
unit is a continuous span of text a human would read as one thought
or one row of a form. Specifically:

A) MULTI-LINE HEADINGS / TITLES that span 2-3 stacked lines but
   belong together are ONE element. Join the lines with a single
   newline "\\n".
     Example A1 (header block, top-left of the page):
       MINISTERO
       DELL'INTERNO
     → one element with text "MINISTERO\\nDELL'INTERNO"
     Example A2 (header block, top-right):
       CARTA
       DI IDENTITÀ
       ELETTRONICA
     → one element with text "CARTA\\nDI IDENTITÀ\\nELETTRONICA"

B) FORM ROWS where a label is followed on the SAME visual row (or
   immediately to the right after a gap of whitespace) by its value
   are ONE element. Preserve a tab-like separation by joining the
   label and value with multiple spaces.
     Example B1:
       Comune        SAN BENEDETTO DEL TRONTO
     → one element "Comune    SAN BENEDETTO DEL TRONTO"
     Example B2:
       Codice Fiscale    PRGLLI21E70Z114M
     → one element "Codice Fiscale    PRGLLI21E70Z114M"
   If a value WRAPS to the next line (because it's long) include
   the wrapped portion in the same element using "\\n":
       Luogo di residenza   VIA TAGLIAMENTO, N. 23 SAN
                            BENEDETTO DEL TRONTO (AP)
     → one element "Luogo di residenza   VIA TAGLIAMENTO, N. 23 SAN\\nBENEDETTO DEL TRONTO (AP)"

C) PARAGRAPHS (multi-line prose) are ONE element. Join the
   constituent lines with single spaces, NOT with "\\n".
     Example C1:
       Conserva questo documento, potrai utilizzarlo in Italia
       fino alla ricezione della tua Carta di Identità Elettronica
       (CIE).
     → one element "Conserva questo documento, potrai utilizzarlo in Italia fino alla ricezione della tua Carta di Identità Elettronica (CIE)."

D) STANDALONE LINES (single-line titles, captions, footers) are
   one element on their own — e.g. the centred title
   "Ricevuta della richiesta CIE".

E) TABLE ROWS: each row is one element per cell. Read across the
   row (left to right), one element per visible cell. A header
   row's cells go above the data row's cells in document order.

============================================================
FONT FAMILY guidance
============================================================
- Look at the actual letter shapes:
    * "serif" — letters have small horizontal/vertical strokes at the
      ends of stems (e.g. Times, Garamond, Cambria, Georgia, Minion).
    * "sans_serif" — letters have clean, flat-ended strokes with no
      serifs (e.g. Arial, Helvetica, Calibri, Open Sans).
    * "monospace" — every character takes equal horizontal width
      (e.g. Courier, Consolas, Menlo).
- `document_font_family` is your best guess for the DOMINANT body
  font of the whole page.
- Per-element `font_family` lets you note when a particular line
  uses a different family. When in doubt, repeat the document-level
  value.

Coordinate frame: pixel positions in the IMAGE'S native size. For
multi-line elements emit the bbox that ENCLOSES THE WHOLE BLOCK
(top of the first line to the bottom of the last line).

============================================================
PER-ELEMENT FIELDS
============================================================
1) Text elements (kind="text"):
   - "text" reproduces the source EXACTLY — same language, diacritics,
     capitalisation, punctuation, numbers, parens, slashes.
   - "alignment" reflects what you actually see for the block:
       a block centred on the page is "center"; a block flush
       against the right margin is "right"; everything else "left".
   - "bold" / "italic" reflect visible weight and slant.
   - "all_caps" is true ONLY when the block is rendered in caps
     (don't guess based on the words being acronyms).
   - "size" is relative to the body text on the page:
       xlarge = main title (e.g. "Ricevuta della richiesta CIE")
       large  = section header
       normal = body text
       small  = fine print, address lines, disclaimers

2) Placeholder elements (kind="placeholder"):
   Whenever a part of the page is a NON-TEXT visual element, emit a
   placeholder with the appropriate label. Set "placeholder_kind"
   and write "text" as the readable label EXACTLY as below:
     coat_of_arms   → "[Coat of Arms]"
     logo           → "[Logo]"
     photo          → "[Photo]"
     stamp          → "[Stamp: <legible text inside the stamp>]"
                       (omit the colon+text if no readable text)
     signature      → "[Signature: <legible name if any>]"
     barcode        → "[Barcode]"
     qr             → "[QR Code]"
     illegible      → "[Illegible Text]"
     handwritten    → "[Handwritten text: <transcription>]"
     blanked_out    → "[Blanked Out]"

   ⚠️ CRITICAL — DO NOT FABRICATE PLACEHOLDERS FOR TEXT:
   If a block of text is READABLE — even if it's stylised, bold,
   small-caps, or sits where a header logo might typically go —
   transcribe it as a TEXT element. Do NOT emit "[Logo]" or
   "[Coat of Arms]" above or beside readable text.
   - Bold heading words like "MINISTERO\\nDELL'INTERNO" in the top
     corner of an Italian government form are TEXT, not a logo.
   - "CARTA\\nDI IDENTITÀ\\nELETTRONICA" in the top-right corner
     of a CIE document is TEXT, not a logo.
   Only emit "[Logo]" when there is a true GRAPHICAL mark
   (illustrative symbol, crest, emblem, brand graphic) with NO
   readable words inside or next to it that you could transcribe.

   Use blanked_out when a field has a value that's been redacted
   with a bar / black box / whiteout so the value isn't visible.
   Emit ONE [Blanked Out] element inline where the redacted value
   would have appeared.

============================================================
QUALITY CONTROLS — STRICT
============================================================
- DO NOT emit fragments. If a word or short string isn't readable
  with confidence, DROP it entirely — never emit a one- or two-
  character segment like "t", "OD", "Ae" or partial words like
  "( Y CARTA". When in doubt, treat the area as a placeholder
  (logo / illegible) instead.
- DO NOT emit a label without its value when the value is clearly
  visible next to it. They go in the SAME element.
- DO NOT translate. DO NOT invent text. DO NOT skip "decorative"
  lines that contain real readable words.

INCLUDE EVERY visible block of text (headers, body, address lines,
contact numbers, fine print, footer disclaimers, signature labels,
stamps). A typical ID/certificate has 15-40 logical elements when
placeholders are included.

EXCLUDE only:
- Machine-readable zones (dense strings of A-Z, 0-9 and '<' such as
  "P<NLD<<<<<<<").
- Pure decorative borders / watermark backgrounds that contain no
  readable words.

Output ONLY the JSON object. No prose, no markdown fences."""


# Patterns that almost always indicate a partial OCR fragment from a
# stylised header / watermark rather than real readable text. Tuned
# against the failure mode seen on Italian CIE documents where the
# CARTA / DI IDENTITÀ / ELETTRONICA header was producing junk like
# "t", "OD", "( Y CARTA", "Ae : ELETTRONICA".
_JUNK_RE = re.compile(
    r"""
    ^                                      # full-string match
    (?:
        [^\w\s]{0,3}                       # leading punctuation
        [A-Za-z]{1,2}                      # 1-2 letters
        [^\w\s]{0,3}                       # trailing punctuation
      |                                    # OR
        [^\w\s]+[A-Za-z]{0,2}              # only punctuation + tiny letters
      |                                    # OR
        [A-Za-z]{1,2}\s*[:.]\s*[A-Za-z]{0,4}  # "Ae :" / "X. Y"
    )
    $
    """,
    re.VERBOSE,
)


def _looks_like_junk(text: str) -> bool:
    """Return True for strings that look like OCR junk fragments.

    Real words and short labels in our reference docs ("Nome", "Sesso",
    "F", "Cognome", "1") need to survive. We're targeting things like
    "t", "OD", "( Y CARTA", "Ae : ELETTRONICA" — partial reads of
    stylised header text that the model occasionally emits even with
    the prompt telling it to drop fragments.
    """
    s = text.strip()
    if not s:
        return True

    # 1) Anything 3+ characters made entirely of letters / spaces /
    #    apostrophes / hyphens is fine (real words and phrases).
    cleaned = s.replace(" ", "").replace("'", "").replace("-", "")
    if len(s) >= 3 and cleaned.isalpha():
        return False

    # 2) 1-2 character strings — junk UNLESS they're a known short
    #    form-field value like "F", "M", "1", "A", "B" (all alpha-
    #    numeric AND uppercase OR digit).
    if len(s) <= 2:
        if s.isalnum() and (s.isdigit() or s.isupper()):
            return False
        return True

    # 3) Strings that start with stray punctuation (e.g. "( Y CARTA",
    #    ") A", ".X") — almost always partial reads.
    if s[0] in "()[]{}/\\<>|" and not s.endswith(")"):
        # Allow normal parens that close, like "(CIE)" or "(GBR)".
        return True

    # 4) Two-letter token followed by ": " or "." then more letters —
    #    classic "Ae : ELETTRONICA" / "X. Y" partial read.
    if _JUNK_RE.match(s):
        return True

    # 5) Letters < 50% of length and contains stray brackets/punct → junk
    letters_or_digits = sum(1 for c in s if c.isalnum())
    if letters_or_digits / max(1, len(s)) < 0.5:
        return True

    return False


def is_available() -> bool:
    """True if we have the API key + library to run a Claude OCR call."""
    if not getattr(settings, "ANTHROPIC_API_KEY", None):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_image(image_path: str) -> list[dict[str, Any]] | None:
    """OCR an image with Claude Vision. Returns a list of
    {"text": str, "bbox": [x0,y0,x1,y1]} dicts in IMAGE-NATIVE
    pixel coordinates, or None if the call failed.
    """
    if not is_available():
        return None

    import anthropic
    from PIL import Image

    # Read the source dimensions. Claude returns bboxes relative to the
    # IMAGE IT SAW, so if we upscale before sending we need to remember
    # the upscaled size and scale bboxes back to the original.
    try:
        with Image.open(image_path) as pil:
            pil.load()
            orig_w, orig_h = pil.size
            mode = pil.mode
            # Upscale documents so Claude can read fine print.
            # ~3000px on the long edge hits a sweet spot: enough
            # resolution that even 8pt body text is legible to the
            # model, while staying well under Claude's 8K image cap.
            long_edge = max(orig_w, orig_h)
            TARGET_LONG_EDGE = 3000
            if long_edge < TARGET_LONG_EDGE:
                scale_up = TARGET_LONG_EDGE / long_edge
                up_w = int(orig_w * scale_up)
                up_h = int(orig_h * scale_up)
                send_img = pil.convert("RGB").resize(
                    (up_w, up_h), Image.LANCZOS
                )
                buf = io.BytesIO()
                send_img.save(buf, format="PNG", optimize=True)
                img_bytes = buf.getvalue()
                media_type = "image/png"
                sent_w, sent_h = up_w, up_h
                logger.info(
                    "Claude OCR: upscaled %dx%d → %dx%d before send "
                    "(x%.2f) for better fine-print recognition",
                    orig_w, orig_h, up_w, up_h, scale_up,
                )
            else:
                # Image is already large enough — send as-is.
                with open(image_path, "rb") as f:
                    img_bytes = f.read()
                ext = image_path.rsplit(".", 1)[-1].lower()
                media_type = {
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "png": "image/png",
                    "gif": "image/gif",
                    "webp": "image/webp",
                }.get(ext, "image/jpeg")
                sent_w, sent_h = orig_w, orig_h
    except Exception as e:
        logger.warning("Claude OCR: couldn't open source image: %s", e)
        return None

    src_w, src_h = orig_w, orig_h  # used for bbox rescaling below
    b64 = base64.standard_b64encode(img_bytes).decode("ascii")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        resp = client.messages.create(
            model=settings.ANTHROPIC_VISION_MODEL,
            # 16K so dense documents (forms, certificates with footer
            # disclaimers, multi-paragraph notices) fit without
            # truncating the JSON mid-line.
            max_tokens=16384,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Return JSON for this image. Read EVERY "
                                "visible line of text including the "
                                "header, body, address, contact numbers, "
                                "registration codes, dates, signature "
                                "labels and footer fine print. "
                                f"Image size as you see it: "
                                f"{sent_w}x{sent_h} px. Use that exact "
                                "coordinate frame for all bboxes."
                            ),
                        },
                    ],
                }
            ],
        )
    except Exception as e:
        logger.warning("Claude OCR API call failed: %s", e)
        return None

    # The response should be a single text block containing the JSON.
    try:
        raw = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                raw += block.text
        raw = raw.strip()
        # Strip accidental markdown fences if any.
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        data = json.loads(raw)
    except Exception as e:
        logger.warning("Claude OCR: bad JSON response: %s", e)
        return None

    declared_w = int(data.get("width") or src_w)
    declared_h = int(data.get("height") or src_h)
    sx = src_w / max(1, declared_w)
    sy = src_h / max(1, declared_h)

    # New v4 shape uses "elements"; fall back to old "lines" for
    # backwards compatibility if the model returns the older format.
    raw_elements = data.get("elements") or data.get("lines") or []

    out: list[dict[str, Any]] = []
    dropped_junk = 0
    for el in raw_elements:
        text = (el.get("text") or "").strip()
        if not text:
            continue
        bbox = el.get("bbox") or [0, 0, 0, 0]
        if len(bbox) != 4:
            continue
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox)
        except Exception:
            continue
        x0 = max(0.0, min(src_w, x0 * sx))
        y0 = max(0.0, min(src_h, y0 * sy))
        x1 = max(0.0, min(src_w, x1 * sx))
        y1 = max(0.0, min(src_h, y1 * sy))
        if x1 <= x0 + 1 or y1 <= y0 + 1:
            continue
        # Safety net: drop obvious OCR-junk fragments even though the
        # prompt forbids them. These come up most often on stylised
        # header text and watermarks where the model produces things
        # like "t", "Ae", "OD", "( Y CARTA". Placeholders (kind=
        # "placeholder") are exempt because they intentionally have
        # short labels like "[Photo]" / "[QR Code]".
        kind = el.get("kind") or "text"
        if kind == "text" and _looks_like_junk(text):
            dropped_junk += 1
            continue
        # Per-element font family with a document-level fallback so we
        # always have a value to render with.
        doc_family = (data.get("document_font_family") or "").lower()
        family = (el.get("font_family") or doc_family or "").lower()
        # Normalise common variants the model might emit.
        family = family.replace("-", "_").replace(" ", "_")
        if family in ("sansserif", "sans"):
            family = "sans_serif"
        if family not in ("serif", "sans_serif", "monospace"):
            family = ""  # downstream will pick a default
        out.append(
            {
                "text": text,
                "bbox": [x0, y0, x1, y1],
                "kind": el.get("kind") or "text",
                "placeholder_kind": el.get("placeholder_kind"),
                "alignment": (el.get("alignment") or "left").lower(),
                "bold": bool(el.get("bold")),
                "italic": bool(el.get("italic")),
                "all_caps": bool(el.get("all_caps")),
                "size": (el.get("size") or "normal").lower(),
                "font_family": family,
            }
        )

    raw_count = len(raw_elements)
    logger.info(
        "Claude Vision OCR (%s): model returned %d raw elements, "
        "%d kept after validation (%d junk fragments dropped), from %s",
        _PROMPT_VERSION,
        raw_count,
        len(out),
        dropped_junk,
        image_path,
    )
    return out
