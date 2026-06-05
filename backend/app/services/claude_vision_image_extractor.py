"""Vision-based image-region cropper.

This is the "claude.ai parity" pre-pass for logos, signatures,
seals, stamps, and photos. Instead of pulling embedded XObjects
out of the PDF (which misses vector-drawn crests) or blindly
cropping wide low-res header/footer strips (which look blurry),
we:

  1. Render each PDF page at 300 DPI as a clean PNG.
  2. Ask Claude Vision to identify image regions on each page
     and return bounding boxes labeled with KIND (crest / logo
     / signature / seal / stamp / photo).
  3. Crop those exact pixel regions from the 300 DPI render
     and save each as a discrete PNG in ./images/.
  4. Return a list the multi-turn rebuild loop can hand back
     to Claude — "this filename is the crest, insert at Cm(2.5);
     this filename is the signature, insert at Cm(5)" etc.

Public entry point:
    extract_image_regions_via_vision(pdf_bytes, dest_dir,
                                     model="claude-opus-4-6")
        -> list[{"kind", "filename", "page", "width_px",
                  "height_px", "suggested_width_cm"}]
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)


# Suggested DOCX widths per kind (used by the prompt + as a hint
# in the returned list so the rebuild loop can size the picture
# consistently).
_SUGGESTED_CM = {
    "crest": 2.5,
    "coat_of_arms": 2.5,
    "logo": 3.0,
    "institutional_logo": 3.0,
    "seal": 3.0,
    "stamp": 3.0,
    "signature": 5.0,
    "photo": 3.0,
    "id_photo": 3.0,
    "qr_code": 2.0,
    "barcode": 4.0,
}

# Render DPI for the page rasterization that we crop from. 300 is
# the sweet spot — sharp enough that 200x200 px crops still look
# good in Word, small enough that bytes don't explode.
_RENDER_DPI = 300


def _render_pdf_pages_at_dpi(pdf_bytes: bytes, dpi: int = _RENDER_DPI) -> list:
    """Return a list of PIL Image objects, one per page, at the
    requested DPI. Empty list on failure."""
    try:
        import fitz  # PyMuPDF
        from PIL import Image
    except Exception as e:
        logger.warning("Vision image extractor: missing dep %s", e)
        return []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.warning("Vision image extractor: PDF open failed: %s", e)
        return []

    pages = []
    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for page_num, page in enumerate(doc, start=1):
            try:
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img = Image.frombytes(
                    "RGB", (pix.width, pix.height), pix.samples
                )
                pages.append(img)
            except Exception as e:
                logger.warning(
                    "Page %d render at %d DPI failed: %s",
                    page_num, dpi, e,
                )
                pages.append(None)
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return pages


def _b64_encode_for_vision(img, max_dim: int = 1568) -> str:
    """Encode a PIL Image as base64 PNG, downscaling if needed so
    the Vision call stays under Anthropic's per-image size cap."""
    from PIL import Image
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


_PROMPT = textwrap.dedent("""
Look at the attached PDF page image(s). Identify EVERY image-like
region on the page — institutional crests / coats of arms,
company logos, round seals, rubber stamps, handwritten signatures,
ID / passport photos, QR codes, and barcodes.

Do NOT identify body text, headings, lines, or table grids as
image regions. Only actual pictures / graphics / handwritten
marks.

For each image region, return a JSON object with these fields:
    "page":   <1-indexed page number>
    "kind":   <one of "crest", "logo", "seal", "stamp",
               "signature", "photo", "qr_code", "barcode">
    "x":      <left pixel coordinate (0 = left edge of page)>
    "y":      <top pixel coordinate (0 = top edge of page)>
    "w":      <width in pixels>
    "h":      <height in pixels>
    "description": <short freeform string, e.g. "Italian Republic
                    crest", "round seal of Florence", "officer's
                    handwritten signature">

The pixel coordinates MUST be in the coordinate system of the
attached image as rendered (NOT the PDF point system). Top-left
is (0, 0). Tight crops only — don't include surrounding text or
whitespace in the bounding box.

Return ONE JSON object wrapped in ```json … ```:
    {"regions": [ {...}, {...}, ... ]}

Empty array if no image regions exist. No prose. No commentary.
Just the JSON block.
""").strip()


def _ask_vision_for_regions(pages, model: str) -> list:
    """Run the Vision call. Returns a list of region dicts as
    received from Claude. Empty list on failure."""
    try:
        import anthropic  # type: ignore
    except Exception:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    # Build content blocks: one image per page + the prompt last.
    valid_pages = [(i + 1, p) for i, p in enumerate(pages) if p is not None]
    if not valid_pages:
        return []

    # Compute the effective image dimensions that the vision call
    # actually sees (after our downscale). Coordinates Claude
    # returns are in THIS coordinate space, not the original.
    sent_dims = {}
    content = []
    for page_num, img in valid_pages:
        from PIL import Image
        w0, h0 = img.size
        # Mirror the downscale logic from _b64_encode_for_vision
        max_dim = 1568
        if max(w0, h0) > max_dim:
            scale = max_dim / max(w0, h0)
            sent_w, sent_h = int(w0 * scale), int(h0 * scale)
        else:
            sent_w, sent_h = w0, h0
        sent_dims[page_num] = (sent_w, sent_h, w0, h0)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": _b64_encode_for_vision(img, max_dim=max_dim),
            },
        })
    content.append({"type": "text", "text": _PROMPT})

    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=8000,
            temperature=0.1,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:
        logger.warning("Vision image-region call failed: %s", e)
        return []

    raw = ""
    for block in resp.content or []:
        if getattr(block, "type", None) == "text":
            raw += getattr(block, "text", "") or ""

    m = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    payload = m.group(1).strip() if m else raw.strip()
    try:
        data = json.loads(payload)
    except Exception:
        logger.warning(
            "Vision image-region response was not JSON: %r", raw[:200]
        )
        return []

    regions = data.get("regions", []) if isinstance(data, dict) else []
    # Attach the sent_w/sent_h so the caller can rescale to the
    # original render coordinates.
    for r in regions:
        if not isinstance(r, dict):
            continue
        page_num = int(r.get("page", 0) or 0)
        if page_num in sent_dims:
            r["_sent_w"], r["_sent_h"], r["_orig_w"], r["_orig_h"] = sent_dims[page_num]
    return [r for r in regions if isinstance(r, dict)]


def _crop_and_save(pages, regions, dest_dir: Path) -> list:
    """Crop each region from its full-resolution page render and
    save as a discrete PNG. Returns the manifest the rebuild loop
    will see."""
    from PIL import Image

    images_dir = dest_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    counters: dict[str, int] = {}

    for r in regions:
        try:
            page_num = int(r.get("page", 0) or 0)
            kind_raw = str(r.get("kind", "")).strip().lower().replace(" ", "_")
            x = int(r.get("x", 0))
            y = int(r.get("y", 0))
            w = int(r.get("w", 0))
            h = int(r.get("h", 0))
            description = str(r.get("description", "")).strip()
        except Exception:
            continue

        if not kind_raw or w <= 0 or h <= 0:
            continue
        # Normalize unknown kinds.
        kind = kind_raw
        if kind in ("coat_of_arms", "national_emblem", "republic_crest"):
            kind = "crest"

        if not (1 <= page_num <= len(pages)) or pages[page_num - 1] is None:
            continue
        page_img = pages[page_num - 1]
        orig_w, orig_h = page_img.size

        # Rescale coords from the (possibly downscaled) image we
        # sent to Vision back to the full-res render.
        sent_w = r.get("_sent_w") or orig_w
        sent_h = r.get("_sent_h") or orig_h
        sx = orig_w / sent_w
        sy = orig_h / sent_h
        rx = max(0, int(x * sx))
        ry = max(0, int(y * sy))
        rw = max(1, int(w * sx))
        rh = max(1, int(h * sy))

        # Pad a tiny margin so we don't cut the very edges of the
        # crest / signature. ~1% of the page width.
        pad = max(2, int(orig_w * 0.01))
        rx = max(0, rx - pad)
        ry = max(0, ry - pad)
        rw = min(orig_w - rx, rw + 2 * pad)
        rh = min(orig_h - ry, rh + 2 * pad)

        if rw <= 0 or rh <= 0:
            continue

        try:
            crop = page_img.crop((rx, ry, rx + rw, ry + rh))
        except Exception as e:
            logger.warning("Crop failed for region %s: %s", r, e)
            continue

        n = counters.get(kind, 0) + 1
        counters[kind] = n
        fname = f"{kind}_{n}.png"
        out_path = images_dir / fname
        try:
            crop.save(str(out_path), format="PNG", optimize=True)
        except Exception as e:
            logger.warning("Save failed for %s: %s", fname, e)
            continue

        manifest.append({
            "kind": kind,
            "filename": fname,
            "page": page_num,
            "width_px": rw,
            "height_px": rh,
            "suggested_width_cm": _SUGGESTED_CM.get(kind, 3.0),
            "description": description,
        })

    return manifest


def extract_image_regions_via_vision(
    pdf_bytes: bytes,
    dest_dir: Path,
    *,
    model: str = "claude-opus-4-6",
) -> list:
    """End-to-end vision-based image extraction.

    Renders the PDF at 300 DPI, asks Claude Vision to identify
    every crest / logo / signature / seal / stamp / photo region
    with a bounding box, crops each one from the high-res render,
    and writes them to dest_dir/images/<kind>_<n>.png.

    Returns the manifest list described in this module's docstring.
    """
    pages = _render_pdf_pages_at_dpi(pdf_bytes, dpi=_RENDER_DPI)
    if not pages:
        logger.info("Vision image extractor: no pages rendered, skipping")
        return []

    regions = _ask_vision_for_regions(pages, model=model)
    logger.info(
        "Vision image extractor: %d region(s) identified across %d page(s)",
        len(regions), len([p for p in pages if p is not None]),
    )
    if not regions:
        return []

    manifest = _crop_and_save(pages, regions, dest_dir)
    logger.info(
        "Vision image extractor: saved %d cropped image(s) to %s/images/",
        len(manifest), dest_dir,
    )
    return manifest


def format_vision_image_list(manifest: list) -> str:
    """Render the multi-turn / single-shot prompt's EXTRACTED IMAGES
    block from the vision manifest."""
    if not manifest:
        return "(no discrete image regions detected)"
    lines = []
    for m in manifest:
        lines.append(
            f"  - kind={m['kind']}, filename=images/{m['filename']}, "
            f"page={m['page']}, width_px={m['width_px']}, "
            f"height_px={m['height_px']}, "
            f"suggested_width=Cm({m['suggested_width_cm']}), "
            f"description={m.get('description', '')!r}"
        )
    return "\n".join(lines)
