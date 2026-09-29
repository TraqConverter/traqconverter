"""Where each translated paragraph sits in the original, and how reliably the original reads there."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

from app.models.document_version import DocumentVersion
from app.models.project import TranslationProject
from app.models.review import ReviewState
from app.models.translation_segment import TranslationSegment
from app.services import claude_params, docx_blocks, source_pages

logger = logging.getLogger(__name__)

VISION_MODEL = os.getenv("REVIEW_VISION_MODEL", claude_params.CLASSIFIER_MODEL)
MATCH_MIN = 0.55
STRONG_MATCH = 0.75
MAX_VISION_PAGES = 12
MAX_PARAS_PER_CALL = 80
RUN_STALE = timedelta(minutes=5)
READINGS = ("high", "medium", "low")
ELEMENT_KINDS = ("stamp", "seal", "signature", "revenue_stamp", "handwriting")

_TOKEN_RE = re.compile(r"[^\W_]+")
_STOP = {
    "the", "of", "and", "in", "on", "at", "to", "for", "by", "a", "an", "is", "no", "with", "from", "this", "that",
    "di", "del", "della", "il", "la", "lo", "le", "e", "in", "per", "da", "con", "de", "el", "los", "las", "y", "en",
    "du", "des", "et", "au", "der", "die", "das", "und", "von", "zu", "im", "do", "da", "dos", "das", "em",
}


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(fold(text)) if len(t) >= 2 or t.isdigit()}


def _weight(tok: str) -> float:
    if any(c.isdigit() for c in tok):
        return 3.0
    if tok in _STOP:
        return 0.3
    return 1.5 if len(tok) >= 6 else 1.0


def _w(toks) -> float:
    return sum(_weight(t) for t in toks)


def document_paragraphs(data: bytes) -> list[dict]:
    """Paragraphs with text, in document order, marking the ones on the certification page."""
    from app.services import docx_certification

    doc = docx_blocks._Doc.load(data)
    cert_ps = {id(p) for unit in docx_certification._marker_units(doc) for p in unit.iter(docx_blocks.w("p"))}
    out = []
    for part in sorted(doc.trees, key=lambda n: (n != "word/document.xml", n)):
        where = "body" if part == "word/document.xml" else ("header" if "header" in part else "footer")
        for p in doc.trees[part].iter(docx_blocks.w("p")):
            bid = docx_blocks._block_id_of(p)
            text = docx_blocks.paragraph_text(p)
            if bid and text.strip():
                out.append({"id": bid, "text": text, "cert": id(p) in cert_ps, "where": where})
    return out


def _frac_box(layout: dict, page_size: dict) -> Optional[list[float]]:
    bbox = layout.get("bbox")
    if not bbox or len(bbox) != 4:
        return None
    kind = layout.get("kind") or ""
    w, h = page_size["width"], page_size["height"]
    if kind == "pdf_claude_line":
        # Claude read a 200 dpi render of the page.
        w_pt = layout.get("page_width_pt") or w
        h_pt = layout.get("page_height_pt") or h
        w, h = w_pt * 200 / 72, h_pt * 200 / 72
    elif kind not in ("pdf_line", "pdf_ocr_line", "image_line"):
        return None
    x0, y0, x1, y1 = (float(v) for v in bbox)
    box = [max(0.0, min(1.0, x0 / w)), max(0.0, min(1.0, y0 / h)), max(0.0, min(1.0, x1 / w)), max(0.0, min(1.0, y1 / h))]
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return [round(v, 4) for v in box]


def segment_boxes(db: Session, project: TranslationProject, info: dict) -> list[dict]:
    rows = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project.id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    out = []
    for s in rows:
        layout = s.layout_meta or {}
        page = int(layout.get("page") or 0)
        box = None
        if info.get("available") and 0 <= page < info["count"]:
            box = _frac_box(layout, info["pages"][page])
        src, tgt = s.source_text or "", s.translated_text or ""
        out.append({
            "index": s.segment_index,
            "page": page,
            "bbox": box,
            "src": src,
            "tgt": tgt,
            "placeholder": layout.get("placeholder_kind") if layout.get("claude_kind") == "placeholder" else None,
            "ocr": layout.get("ocr_source") == "claude" or layout.get("kind") in ("pdf_ocr_line", "image_line"),
            "toks": tokens(tgt) | tokens(src),
            "base": tokens(tgt) or tokens(src),
        })
    return out


def _union(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def match_segments(paras: list[dict], segs: list[dict]) -> dict[str, dict]:
    """Paragraph -> source box from extraction segments, by shared words, names and numbers."""
    boxed = [s for s in segs if s["bbox"]]
    out: dict[str, dict] = {}
    last = -1
    for p in paras:
        a = tokens(p["text"])
        wa = _w(a)
        if wa < 1:
            continue
        scored = []
        for s in boxed:
            inter = a & s["toks"]
            if not inter:
                continue
            wi = _w(inter)
            cov_para = wi / wa
            cov_seg = wi / max(_w(s["base"] | inter), 1e-6)
            score = 0.6 * cov_para + 0.4 * cov_seg
            # Prefer reading order: a line far before the previous match is usually a repeated word elsewhere.
            if last >= 0 and s["index"] < last - 3:
                score -= 0.08
            scored.append((score, -abs(s["index"] - (last + 1)), s, inter, cov_seg))
        if not scored:
            continue
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, _, best, inter, best_seg_cov = scored[0]
        chosen = [best]
        covered = set(inter)
        for _, _, s, s_inter, cov_seg in scored[1:]:
            if s["page"] == best["page"] and abs(s["index"] - best["index"]) <= 6 and cov_seg >= 0.7 and _w(s_inter - covered) > 0:
                chosen.append(s)
                covered |= s_inter
        confidence = (_w(covered) / wa) * (0.5 + 0.5 * best_seg_cov)
        if confidence < MATCH_MIN:
            continue
        out[p["id"]] = {
            "page": best["page"],
            "bbox": [round(v, 4) for v in _union([s["bbox"] for s in chosen])],
            "confidence": round(min(1.0, confidence), 2),
            "via": "segments",
            "segments": sorted(s["index"] for s in chosen),
        }
        if confidence >= STRONG_MATCH:
            last = best["index"]
    return out


def candidate_pages(paras: list[dict], blocks: dict, page_count: int) -> dict[str, list[int]]:
    """Pages a paragraph can be on: its own match, else between the matched paragraphs around it."""
    out: dict[str, list[int]] = {}
    known = [(i, blocks[p["id"]]["page"]) for i, p in enumerate(paras) if blocks.get(p["id"], {}).get("page") is not None]
    for i, p in enumerate(paras):
        entry = blocks.get(p["id"])
        if entry and entry.get("page") is not None:
            out[p["id"]] = [entry["page"]]
            continue
        if page_count <= 1:
            out[p["id"]] = [0]
            continue
        before = [pg for j, pg in known if j < i]
        after = [pg for j, pg in known if j > i]
        if before or after:
            lo = before[-1] if before else 0
            hi = after[0] if after else page_count - 1
            out[p["id"]] = list(range(min(lo, hi), max(lo, hi) + 1))
        else:
            guess = int(i * page_count / max(len(paras), 1))
            out[p["id"]] = [pg for pg in (guess - 1, guess, guess + 1) if 0 <= pg < page_count]
    return out


_VISION_SYSTEM = """You help a certified translator review a translation of an official document. You see one \
page of the ORIGINAL document and a list of paragraphs of the TRANSLATION (id and text). For each paragraph, find \
the region of the page it translates and judge how reliably the original can be read in that region.

For each listed paragraph:
- found: false when its content is not on this page.
- x0, y0, x1, y1: pixel box on this image enclosing all of the original text (or the stamp, seal or signature a \
bracketed note such as [Stamp: ...] or [Signature] describes). Tight but complete; for a table cell, the cell.
- reading: "high" when the original there is crisp printed text; "medium" when it is small or faint but every \
character is still certain; "low" when any digit, letter, date or name there cannot be read with certainty: \
smudged, blurred or covered digits, faded or partial stamp text, hard handwriting, text under a stamp, a \
low-resolution area. A translator signs for every character, so when in doubt choose low.
- reason: for medium or low, a few words saying exactly what is uncertain (e.g. "digits after 55 smudged", \
"stamp ring text faded"); "" for high.

Also list every stamp, seal, signature, revenue/duty stamp and handwritten note visible on the page in \
"elements", with its box, the legible text in it ("" if none), how readable that text is, and block_id: the id of \
the translation paragraph that notes it, or "" if no paragraph does."""

_BOX = {"x0": {"type": "integer"}, "y0": {"type": "integer"}, "x1": {"type": "integer"}, "y1": {"type": "integer"}}
VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "found": {"type": "boolean"},
                    **_BOX,
                    "reading": {"type": "string", "enum": list(READINGS)},
                    "reason": {"type": "string"},
                },
                "required": ["id", "found", "x0", "y0", "x1", "y1", "reading", "reason"],
                "additionalProperties": False,
            },
        },
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(ELEMENT_KINDS)},
                    **_BOX,
                    "text": {"type": "string"},
                    "reading": {"type": "string", "enum": list(READINGS)},
                    "block_id": {"type": "string"},
                },
                "required": ["kind", "x0", "y0", "x1", "y1", "text", "reading", "block_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["paragraphs", "elements"],
    "additionalProperties": False,
}


def _norm_box(item: dict, width: int, height: int) -> Optional[list[float]]:
    try:
        x0, y0, x1, y1 = (float(item[k]) for k in ("x0", "y0", "x1", "y1"))
    except (KeyError, TypeError, ValueError):
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    box = [x0 / width, y0 / height, x1 / width, y1 / height]
    box = [round(max(0.0, min(1.0, v)), 4) for v in box]
    if box[2] - box[0] < 0.003 or box[3] - box[1] < 0.003:
        return None
    return box


def vision_page(project: TranslationProject, page: int, paras: list[dict], model: Optional[str] = None) -> dict:
    """One structured vision call for one page: boxes and reading confidence per paragraph, plus stamps and signatures."""
    key = claude_params.api_key()
    if not key:
        raise RuntimeError("AI is not configured")
    image = source_pages.page_jpeg_for_model(project, page)
    if not image:
        raise RuntimeError("Page image unavailable")
    jpeg, width, height = image
    model = model or VISION_MODEL
    listing = "\n".join(f"{p['id']}: {' '.join(p['text'].split())[:400]}" for p in paras[:MAX_PARAS_PER_CALL])
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}},
        {
            "type": "text",
            "text": f"Image size: {width}x{height} px. Target language of the translation: "
            f"{project.target_language or 'unknown'}.\n\nTRANSLATION PARAGRAPHS\n{listing}",
        },
    ]
    max_tokens = min(16000, 1200 + 110 * len(paras))
    started = time.monotonic()
    resp = claude_params.create_message(
        anthropic.Anthropic(api_key=key),
        model=model,
        max_tokens=max_tokens,
        system=_VISION_SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": VISION_SCHEMA}},
        **claude_params.request_params(model, max_tokens=max_tokens),
    )
    claude_params.log_usage("source_map", resp)
    if resp.stop_reason == "refusal":
        raise RuntimeError("The model declined")
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    data = json.loads(raw)
    known = {p["id"] for p in paras}
    blocks = {}
    for item in data.get("paragraphs") or []:
        bid = item.get("id")
        if bid not in known:
            continue
        box = _norm_box(item, width, height) if item.get("found") else None
        reading = item.get("reading") if item.get("reading") in READINGS else "high"
        blocks[bid] = {
            "page": page if box else None,
            "bbox": box,
            "reading": reading if box else None,
            "reason": (item.get("reason") or "").strip()[:160] if box and reading != "high" else "",
        }
    elements = []
    for el in data.get("elements") or []:
        box = _norm_box(el, width, height)
        if not box or el.get("kind") not in ELEMENT_KINDS:
            continue
        elements.append({
            "page": page,
            "bbox": box,
            "kind": el["kind"],
            "text": (el.get("text") or "").strip()[:200],
            "reading": el.get("reading") if el.get("reading") in READINGS else "high",
            "block_id": el.get("block_id") if el.get("block_id") in known else "",
        })
    usage = getattr(resp, "usage", None)
    return {
        "blocks": blocks,
        "elements": elements,
        "seconds": round(time.monotonic() - started, 2),
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "model": model,
    }


def get_state(db: Session, project: TranslationProject, lock: bool = False) -> ReviewState:
    """The project's review row, reset when the source file changed."""
    q = db.query(ReviewState).filter(ReviewState.project_id == project.id)
    if lock:
        q = q.with_for_update()
    state = q.first()
    if state is None:
        state = ReviewState(project_id=project.id, source_key=project.file_path, map_revision=0, updated_at=datetime.utcnow())
        db.add(state)
        db.flush()
    elif state.source_key != project.file_path:
        state.source_key = project.file_path
        state.source_map = None
        state.names = None
        state.untranslated = None
        state.checks = None
        state.map_revision = (state.map_revision or 0) + 1
    return state


def _empty_map() -> dict:
    return {"status": "ready", "blocks": {}, "elements": [], "scan": None, "started_at": None, "error": None, "runs": []}


def current_data(db: Session, project: TranslationProject) -> Optional[bytes]:
    from app.services.document_editor import _download

    row = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.project_id == project.id, DocumentVersion.version == project.document_version)
        .first()
    )
    return _download(row.s3_key) if row else None


def _needs_vision(entry: Optional[dict], scan: bool) -> bool:
    if entry and entry.get("tried"):
        return False
    if not entry or entry.get("page") is None:
        return True
    return scan and entry.get("reading") is None


def refresh(db: Session, project: TranslationProject, data: bytes) -> tuple[dict, list[str]]:
    """Fill in cheap matches for new paragraphs; return the map and the paragraph ids still needing the vision pass."""
    state = get_state(db, project, lock=True)
    smap = dict(state.source_map or _empty_map())
    blocks = dict(smap.get("blocks") or {})
    paras = [p for p in document_paragraphs(data) if not p["cert"]]
    info = source_pages.page_info(project)
    if not info.get("available"):
        smap.update(status="unavailable", blocks={}, elements=[])
        if state.source_map != smap:
            state.source_map = smap
            state.updated_at = datetime.utcnow()
        db.commit()
        return smap, []
    if smap.get("scan") is None:
        smap["scan"] = len(source_pages.text_layer(project).strip()) < 40
    missing = [p for p in paras if p["id"] not in blocks]
    changed = False
    if missing:
        by_text = {}
        for p in paras:
            entry = blocks.get(p["id"])
            if entry and entry.get("page") is not None:
                by_text.setdefault(" ".join(fold(p["text"]).split()), entry)
        matched = match_segments(paras, segment_boxes(db, project, info))
        for p in missing:
            twin = by_text.get(" ".join(fold(p["text"]).split()))
            if twin:
                blocks[p["id"]] = {**twin, "copied": True}
            elif p["id"] in matched:
                blocks[p["id"]] = matched[p["id"]]
            else:
                blocks[p["id"]] = {"page": None, "bbox": None}
        changed = True
    todo = [p["id"] for p in paras if _needs_vision(blocks.get(p["id"]), bool(smap.get("scan")))]
    running = smap.get("status") == "running" and smap.get("started_at") and (
        datetime.utcnow() - datetime.fromisoformat(smap["started_at"]) < RUN_STALE
    )
    start = bool(todo) and not running and bool(claude_params.api_key())
    if start:
        smap["status"] = "running"
        smap["started_at"] = datetime.utcnow().isoformat()
        changed = True
    elif not running and smap.get("status") == "running":
        smap["status"] = "ready"
        changed = True
    if changed:
        smap["blocks"] = blocks
        state.source_map = smap
        state.map_revision = (state.map_revision or 0) + 1
        state.updated_at = datetime.utcnow()
    db.commit()
    return smap, todo if start else []


def run_vision(project_id, block_ids: list[str]) -> None:
    """Background: the per-page vision pass for `block_ids`, saved page by page."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        project = db.query(TranslationProject).filter(TranslationProject.id == project_id).first()
        if not project:
            return
        data = current_data(db, project)
        state = get_state(db, project)
        smap = state.source_map or _empty_map()
        db.commit()
        if not data:
            return _finish(db, project, {}, [], set(), None, "No document")
        paras = [p for p in document_paragraphs(data) if not p["cert"]]
        wanted = set(block_ids)
        blocks = smap.get("blocks") or {}
        info = source_pages.page_info(project)
        pages = candidate_pages(paras, blocks, info.get("count", 0))
        full = not any(b.get("tried") for b in blocks.values())
        by_page: dict[int, list[dict]] = {}
        for p in paras:
            if p["id"] in wanted:
                for pg in pages.get(p["id"], []):
                    by_page.setdefault(pg, []).append(p)
        error = None
        for page in sorted(by_page)[:MAX_VISION_PAGES]:
            try:
                result = vision_page(project, page, by_page[page])
            except Exception as e:
                logger.exception("Source map vision pass failed (project=%s page=%s)", project_id, page)
                error = str(e)[:200]
                continue
            run = {k: result[k] for k in ("seconds", "input_tokens", "output_tokens", "model")}
            run["page"] = page
            _finish(db, project, result["blocks"], result["elements"] if full else None, set(), run, None, page=page)
        _finish(db, project, {}, None, wanted, None, error, done=True)
    except Exception:
        db.rollback()
        logger.exception("Source map run failed (project=%s)", project_id)
        try:
            project = db.query(TranslationProject).filter(TranslationProject.id == project_id).first()
            if project:
                _finish(db, project, {}, None, set(block_ids), None, "Mapping failed", done=True)
        except Exception:
            db.rollback()
    finally:
        db.close()


def _finish(db, project, found: dict, elements, tried: set, run, error, page=None, done=False) -> None:
    state = get_state(db, project, lock=True)
    smap = dict(state.source_map or _empty_map())
    blocks = dict(smap.get("blocks") or {})
    for bid, v in found.items():
        entry = dict(blocks.get(bid) or {})
        if v.get("bbox"):
            keep_text_box = entry.get("via") == "segments" and (entry.get("confidence") or 0) >= STRONG_MATCH
            if not keep_text_box or entry.get("page") != v["page"]:
                entry.update(page=v["page"], bbox=v["bbox"], confidence=0.7, via="vision")
            entry.update(reading=v["reading"], reason=v["reason"])
        entry["tried"] = True
        blocks[bid] = entry
    for bid in tried:
        if bid in blocks:
            blocks[bid] = {**blocks[bid], "tried": True}
    if elements is not None and page is not None:
        smap["elements"] = [e for e in smap.get("elements") or [] if e.get("page") != page] + elements
    if run:
        smap["runs"] = (smap.get("runs") or [])[-20:] + [run]
    if error:
        smap["error"] = error
    if done:
        smap["status"] = "ready"
    smap["blocks"] = blocks
    state.source_map = smap
    state.map_revision = (state.map_revision or 0) + 1
    state.updated_at = datetime.utcnow()
    db.commit()


def public_view(smap: dict, paras: list[dict], revision: int, version: int) -> dict:
    ids = {p["id"] for p in paras}
    blocks = {}
    for bid, e in (smap.get("blocks") or {}).items():
        if bid in ids and e.get("page") is not None and e.get("bbox"):
            blocks[bid] = {
                "page": e["page"],
                "bbox": e["bbox"],
                "confidence": e.get("confidence", 0.7),
                "reading": e.get("reading") or "high",
                "reason": e.get("reason") or "",
            }
    status = smap.get("status") or "ready"
    return {
        "status": "pending" if status == "running" else status,
        "version": version,
        "revision": revision,
        "blocks": blocks,
        "elements": [{k: e[k] for k in ("page", "bbox", "kind", "text", "reading", "block_id")} for e in smap.get("elements") or []],
    }
