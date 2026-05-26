"""Layout planner — turn a flat list of translated OCR elements into a
structured DOCX skeleton via Claude.

Why this exists
---------------
Our OCR returns a flat list of text + bbox + style elements. The
existing renderer flows them top-to-bottom as paragraphs, which loses
all column / row / table structure. Reference outputs from the user's
reference document need things like:

  * a 2-column header row (MINISTERO/DELL'INTERNO ‖ CARTA/DI IDENTITÀ/
    ELETTRONICA)
  * centered titles
  * right-aligned lines (Numero di Serie ...)
  * a "photo column on the left, form rows on the right" two-column
    section
  * a bordered parent/guardian TABLE
  * a centered footer

Rather than write a layout-clustering algorithm we hand the element
list back to Claude (vision-free this time — text + bbox is enough)
and ask it to plan a DOCX-shaped JSON tree. The renderer then turns
that tree into python-docx paragraphs and tables.

Failure mode: if the planner errors or the JSON is malformed, the
caller falls back to the linear renderer.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


_PLANNER_VERSION = "v1"


_SYSTEM_PROMPT = """You are a DOCX layout planner. Given a flat list of \
text elements extracted from a document image (each has an id, the \
ORIGINAL source text, the TRANSLATED text, a bounding box in pixel \
coordinates [x0,y0,x1,y1], and basic style flags), produce a STRUCTURED \
JSON layout that, when rendered as a DOCX, closely reproduces the visual \
shape of the original document.

Coordinate frame: pixel coordinates in the source image, with (0,0) at \
the top-left and Y increasing downward. The full page width is given to \
you as "page_width".

Output shape (strict JSON, no prose, no fences):

{
  "blocks": [
    <block>, <block>, ...
  ]
}

A <block> is one of:

A) Paragraph:
   { "kind": "paragraph",
     "id": <element id>,
     "alignment": "left" | "center" | "right",
     "indent_mm": <number, optional>,
     "spacing_before_pt": <number, optional> }

B) Two-or-more-column row (one visual row with N side-by-side columns):
   { "kind": "row",
     "columns": [
       { "width_pct": <0-100>,
         "alignment": "left" | "center" | "right",
         "blocks": [<block>, <block>, ...] },
       ...
     ] }

C) Table (gridded, with optional borders):
   { "kind": "table",
     "border": true | false,
     "rows": [
       [ <cell>, <cell>, ... ],
       [ <cell>, <cell>, ... ],
       ...
     ] }
   where <cell> is:
     { "id": <element id>, "alignment": "left" | "center" | "right" }
   OR
     { "text": "<literal text>", "alignment": "..." }   # for empty/spacer cells

D) Spacer (small vertical gap):
   { "kind": "spacer", "height_mm": <number> }

RULES:

1) Use EVERY element id exactly once across the whole "blocks" tree.
   Don't drop elements. Don't duplicate elements.

2) Detect two-column header layouts: if you see two text blocks near
   the top of the page, one at the left edge and one at the right edge
   (different x0 ranges, similar y range), emit them as a "row" with
   two columns.

3) Detect form rows: a label like "Comune" near x≈200 followed by a
   value like "SAN BENEDETTO DEL TRONTO" near x≈350 on the same y
   should be a TWO-COLUMN ROW with the label as the left column and
   value as the right. If the document has many of these consecutive
   form rows, group them into ONE table with two columns instead of
   many separate rows — that produces cleaner output.

4) Detect a PHOTO + FORM layout: if there's a [Photo] placeholder at
   the left side of the page and a stack of form rows to its right
   spanning the same Y range, emit ONE row with:
     column 1 (≈25%): the photo placeholder paragraph
     column 2 (≈75%): the table of form rows
   Same pattern applies to a QR code or stamp sitting next to text.

5) Detect parent/guardian style TABLES: when you see a sequence of
   short header words ("nome e cognome", "estremi del documento",
   "firma") followed by data rows, emit them as a single TABLE with
   border:true.

6) CENTERED titles (page-centered, large font, often bold) → a
   paragraph with alignment "center".

7) RIGHT-aligned standalone elements (e.g. "Numero di Serie XYZ"
   at the right edge of the page) → paragraph alignment "right".

8) Place elements in TOP-DOWN reading order. Elements at similar
   Y belong on the same row.

9) Use ONLY the element ids that appear in the input.

10) Return JSON only — no markdown, no commentary."""


def is_available() -> bool:
    if not getattr(settings, "ANTHROPIC_API_KEY", None):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def plan_layout(
    elements: list[dict[str, Any]],
    *,
    page_width: float,
    page_height: float,
) -> dict[str, Any] | None:
    """Ask Claude to plan a DOCX layout for the given OCR elements.

    `elements` is a list of dicts: each must have keys
    `id` (int), `source` (str), `translated` (str), `bbox` (4-tuple of
    floats), and optional style flags (alignment, bold, italic, size,
    all_caps, kind). Returns a dict with a "blocks" tree (the same
    shape described in the system prompt) or None on failure.
    """
    if not is_available():
        return None
    if not elements:
        return None

    import anthropic

    # Compact each element to keep the prompt cheap.
    compact = []
    for el in elements:
        compact.append(
            {
                "id": el["id"],
                "source": (el.get("source") or "")[:300],
                "translated": (el.get("translated") or "")[:300],
                "bbox": [round(float(v), 1) for v in (el.get("bbox") or [0, 0, 0, 0])],
                "alignment": el.get("alignment") or "left",
                "bold": bool(el.get("bold")),
                "italic": bool(el.get("italic")),
                "all_caps": bool(el.get("all_caps")),
                "size": el.get("size") or "normal",
                "kind": el.get("kind") or "text",
            }
        )

    user_payload = {
        "page_width": page_width,
        "page_height": page_height,
        "elements": compact,
    }

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    try:
        resp = client.messages.create(
            model=settings.ANTHROPIC_VISION_MODEL,
            max_tokens=8192,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Plan the DOCX layout for these elements. "
                                "Return strict JSON.\n\n"
                                + json.dumps(user_payload, ensure_ascii=False)
                            ),
                        }
                    ],
                }
            ],
        )
    except Exception as e:
        logger.warning("Layout planner API call failed: %s", e)
        return None

    try:
        raw = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                raw += block.text
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        plan = json.loads(raw)
    except Exception as e:
        logger.warning("Layout planner: bad JSON response: %s", e)
        return None

    if not isinstance(plan, dict) or "blocks" not in plan:
        logger.warning("Layout planner: response missing 'blocks' key")
        return None

    # Sanity check: planner must reference every element id at most
    # once and not invent new ones.
    valid_ids = {el["id"] for el in elements}
    referenced: list[int] = []
    _collect_ids(plan.get("blocks") or [], referenced)
    extra = [i for i in referenced if i not in valid_ids]
    if extra:
        logger.warning(
            "Layout planner: response references unknown ids %s — discarding",
            extra[:5],
        )
        return None
    seen_count: dict[int, int] = {}
    for i in referenced:
        seen_count[i] = seen_count.get(i, 0) + 1
    dupes = [i for i, n in seen_count.items() if n > 1]
    if dupes:
        logger.warning(
            "Layout planner: duplicated ids %s — discarding",
            dupes[:5],
        )
        return None
    missing = sorted(valid_ids - set(referenced))
    if missing:
        # Append a fallback linear section with the missing ids so we
        # never silently drop content.
        logger.info(
            "Layout planner: appending %d unplaced elements as linear tail",
            len(missing),
        )
        plan.setdefault("blocks", []).append({"kind": "spacer", "height_mm": 3})
        for mid in missing:
            plan["blocks"].append(
                {"kind": "paragraph", "id": mid, "alignment": "left"}
            )

    logger.info(
        "Layout planner (%s): produced %d top-level blocks for %d elements",
        _PLANNER_VERSION,
        len(plan.get("blocks") or []),
        len(elements),
    )
    return plan


def _collect_ids(blocks: list[Any], out: list[int]) -> None:
    """Walk the planner's tree and gather every referenced element id."""
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        kind = b.get("kind")
        if kind == "paragraph":
            try:
                out.append(int(b["id"]))
            except (KeyError, TypeError, ValueError):
                pass
        elif kind == "row":
            for col in b.get("columns") or []:
                if isinstance(col, dict):
                    _collect_ids(col.get("blocks") or [], out)
        elif kind == "table":
            for row in b.get("rows") or []:
                for cell in row or []:
                    if isinstance(cell, dict) and "id" in cell:
                        try:
                            out.append(int(cell["id"]))
                        except (TypeError, ValueError):
                            pass
