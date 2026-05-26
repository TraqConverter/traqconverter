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


_PLANNER_VERSION = "v2-aggressive-tables"


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

============================================================
CRITICAL — THIS IS A LAYOUT TASK, NOT A LIST TASK
============================================================
The DEFAULT for any block of text is NOT a "paragraph". Most
documents have visual structure (columns, tables, side-by-side
blocks) and your job is to recreate it. If you emit only
paragraphs you have FAILED this task.

You MUST use "row" blocks for ANY case where two or more elements
share a similar Y coordinate (their y0 values differ by less than
20% of the average element height) but have clearly different X
coordinates. Examples:
  - A heading at top-left and another heading at top-right.
  - A label and its value separated by horizontal space.
  - A photo placeholder at the left and form rows at its right.
  - A right-aligned element ([QR Code], [Stamp]) next to body text.

You MUST use "table" blocks when you see ≥ 3 consecutive form rows
(same shape: label on the left, value on the right, aligned X
positions). Group them into one table with two columns. Cleaner
than many separate rows.

You MUST use "table" with border:true when you see a parent/guardian
style data section: a header row of column titles ("nome e cognome",
"estremi del documento", "firma") followed by data rows.

============================================================
DETECTION RECIPES
============================================================
Given the page_width W:

1) "Two-column header at top" — for any two elements where
   y_avg < page_height * 0.15 AND one has x0 < W*0.25 AND the
   other has x1 > W*0.75 → "row" with [left_col, right_col].

2) "Centered title" — for any element with
   |((x0+x1)/2) - W/2| < W*0.10 AND text width < W*0.6 → paragraph
   with alignment "center". Often size "large" / "xlarge".

3) "Right-aligned standalone" — for any element with x1 > W*0.85
   AND its x0 > W*0.50 AND it's the only element on its Y row →
   paragraph with alignment "right". Examples: "Numero di Serie",
   "[QR Code]", "[Stamp]".

4) "Form table" — if you see 3+ consecutive elements where:
       - each contains BOTH a label-like prefix AND a value-like
         suffix separated by 2+ spaces (e.g. "Comune    SAN
         BENEDETTO DEL TRONTO")
   → emit ONE table block, two columns, one row per element.
     For each row, SPLIT the element text on the multi-space gap
     and put the label in column 1 (alignment "left") and the
     value in column 2 (alignment "left"). Each cell references
     the SAME element id; we'll handle the split at render time
     via {"id": <id>, "alignment": "left"} for column 1 and
     {"id": <id>, "alignment": "left"} again for column 2. (Yes
     this duplicates the id — set "split_column": "label" or
     "value" on each cell so the renderer knows which half to
     show.)

5) "Photo + form composite" — if a [Photo] placeholder has
   y0 < W*0.40 and x1 < W*0.30 AND there are 4+ form-row elements
   to its right (their x0 > W*0.25 and they span y0..(photo.y1+50))
   → emit ONE "row" with two columns:
       col 1 (≈25%): paragraph with the photo id
       col 2 (≈75%): table of the form rows

6) "Parent/guardian table" — look for elements like
   "nome e cognome" / "estremi del documento" / "firma" with
   alignment "left" on the same Y. Treat the next 1-3 rows of
   data as table data rows. Emit ONE table with border:true,
   3 columns.

============================================================
OUTPUT RULES
============================================================
- Use EVERY element id exactly once across the whole "blocks" tree.
  Don't drop. Don't duplicate. (Form-table split-cells are an
  exception: those CAN reference an id twice with different
  "split_column" values.)
- Place elements in TOP-DOWN reading order.
- Use ONLY ids that appear in the input.
- Return JSON only — no markdown, no commentary, no preamble."""


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
    # Duplicate ids are normally disallowed, but form-table cells can
    # legitimately reference the same id twice (label half + value
    # half). The renderer reads "split_column" to pick which side to
    # show. We only error out if there's a duplicate that isn't part
    # of a split-column form table.
    seen_count: dict[int, int] = {}
    for i in referenced:
        seen_count[i] = seen_count.get(i, 0) + 1
    dupes = [i for i, n in seen_count.items() if n > 1]
    if dupes:
        if not _all_dupes_are_split_columns(plan.get("blocks") or [], dupes):
            logger.warning(
                "Layout planner: duplicated ids %s outside split cells — discarding",
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

    # Diagnostic: log the SHAPE of the plan so we can see whether
    # Claude is actually producing rows/tables or just paragraphs.
    shape = _count_block_kinds(plan.get("blocks") or [])
    logger.info(
        "Layout planner (%s): %d top-level blocks for %d elements — "
        "paragraphs=%d rows=%d tables=%d tables_bordered=%d spacers=%d",
        _PLANNER_VERSION,
        len(plan.get("blocks") or []),
        len(elements),
        shape["paragraph"],
        shape["row"],
        shape["table"],
        shape["table_bordered"],
        shape["spacer"],
    )
    return plan


def _count_block_kinds(blocks: list[Any]) -> dict[str, int]:
    """Walk the planner tree and count block kinds — useful for
    diagnosing 'why is the rebuild flat?'."""
    out = {
        "paragraph": 0,
        "row": 0,
        "table": 0,
        "table_bordered": 0,
        "spacer": 0,
    }
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        kind = b.get("kind", "paragraph")
        if kind == "paragraph":
            out["paragraph"] += 1
        elif kind == "row":
            out["row"] += 1
            for col in b.get("columns") or []:
                if isinstance(col, dict):
                    sub = _count_block_kinds(col.get("blocks") or [])
                    for k, v in sub.items():
                        out[k] += v
        elif kind == "table":
            out["table"] += 1
            if b.get("border"):
                out["table_bordered"] += 1
        elif kind == "spacer":
            out["spacer"] += 1
    return out


def _all_dupes_are_split_columns(
    blocks: list[Any], dupe_ids: list[int]
) -> bool:
    """True iff every duplicated id appears ONLY inside table cells
    that carry a "split_column" hint. Lets us allow form-table label
    + value splits without permitting arbitrary duplication."""
    dupe_set = set(dupe_ids)
    return _walk_check_dupes(blocks, dupe_set)


def _walk_check_dupes(blocks: list[Any], dupe_set: set[int]) -> bool:
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        kind = b.get("kind", "paragraph")
        if kind == "paragraph":
            try:
                eid = int(b.get("id"))
            except (TypeError, ValueError):
                continue
            if eid in dupe_set:
                return False  # dup outside a split-column cell
        elif kind == "row":
            for col in b.get("columns") or []:
                if isinstance(col, dict):
                    if not _walk_check_dupes(col.get("blocks") or [], dupe_set):
                        return False
        elif kind == "table":
            for row in b.get("rows") or []:
                for cell in row or []:
                    if isinstance(cell, dict) and "id" in cell:
                        try:
                            eid = int(cell["id"])
                        except (TypeError, ValueError):
                            continue
                        if eid in dupe_set and not cell.get("split_column"):
                            return False
    return True


def _collect_ids(blocks: list[Any], out: list[int]) -> None:
    """Walk the planner's tree and gather every referenced element id.

    Cells carrying split_column ("label" or "value") count as ONE
    reference toward coverage even when the same id appears in both
    halves of a form-table row.
    """
    seen_split: set[int] = set()
    _collect_ids_inner(blocks, out, seen_split)


def _collect_ids_inner(
    blocks: list[Any], out: list[int], seen_split: set[int]
) -> None:
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
                    _collect_ids_inner(col.get("blocks") or [], out, seen_split)
        elif kind == "table":
            for row in b.get("rows") or []:
                for cell in row or []:
                    if isinstance(cell, dict) and "id" in cell:
                        try:
                            eid = int(cell["id"])
                        except (TypeError, ValueError):
                            continue
                        if cell.get("split_column"):
                            # Count split cells once even if both
                            # label + value halves reference the same
                            # id.
                            if eid not in seen_split:
                                out.append(eid)
                                seen_split.add(eid)
                        else:
                            out.append(eid)
