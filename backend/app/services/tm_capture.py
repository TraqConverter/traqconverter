"""Approved translations from the editor: map document paragraphs back to their source lines and store the pairs."""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.document_version import DocumentVersion
from app.models.project import TranslationProject
from app.models.translation_segment import TranslationSegment
from app.services import source_map, tm_keys
from app.services import translation_memory_service as tm

logger = logging.getLogger(__name__)

ACCEPT = 0.8
ACCEPT_WITH_MAP = 0.65
MARGIN = 0.1
SHORT_WEIGHT = 3.0
_NOTATION_ONLY = re.compile(r"^\s*(\[[^\]]*\]\s*)+$")
_DIGITS = re.compile(r"\d+")


def _paragraph_texts(data: bytes) -> dict[str, str]:
    from app.services.learning import _paragraphs

    return _paragraphs(data)


def _digits(text: str) -> list[str]:
    return sorted(d.lstrip("0") or "0" for d in _DIGITS.findall(text or ""))


def _dice(a: set, b: set) -> float:
    total = source_map._w(a) + source_map._w(b)
    return 2 * source_map._w(a & b) / total if total else 0.0


def usable_pair(source: str, target: str) -> bool:
    """A source/translation pair worth keeping: real text on both sides, same numbers, plausible lengths."""
    source, target = tm_keys.normalise_text(source), tm_keys.normalise_text(target)
    if not source or not target or len(source) > tm_keys.MAX_SOURCE_CHARS:
        return False
    if _NOTATION_ONLY.match(source) or _NOTATION_ONLY.match(target):
        return False
    if not any(c.isalpha() for c in source) or not any(c.isalpha() for c in target):
        return False
    if _digits(source) != _digits(target):
        return False
    return 0.4 <= len(target) / len(source) <= 2.5


class SegmentIndex:
    """The project's extracted source lines and their first-pass translations."""

    def __init__(self, segments: list[tuple[int, str, str]]):
        self.segs = [(i, s or "", t or "") for i, s, t in segments]
        self.by_target: dict[str, set[str]] = {}
        for _, s, t in self.segs:
            if t.strip() and s.strip():
                self.by_target.setdefault(tm_keys.normalise_text(t), set()).add(tm_keys.normalise_text(s))
        self.tokens = [source_map.tokens(t) for _, _, t in self.segs]

    @classmethod
    def for_project(cls, db: Session, project: TranslationProject) -> "SegmentIndex":
        rows = (
            db.query(TranslationSegment.segment_index, TranslationSegment.source_text, TranslationSegment.translated_text)
            .filter(TranslationSegment.project_id == project.id)
            .order_by(TranslationSegment.segment_index)
            .all()
        )
        return cls([(r[0], r[1], r[2]) for r in rows])

    def _runs(self, text: str) -> list[tuple[float, int, int]]:
        """(similarity, start, length) for runs of up to 4 consecutive segments sharing words with `text`."""
        toks = source_map.tokens(text)
        out = []
        for start in range(len(self.segs)):
            if not toks & self.tokens[start]:
                continue
            joined: set = set()
            for n in range(1, tm.MAX_WINDOW + 1):
                if start + n > len(self.segs):
                    break
                joined = joined | self.tokens[start + n - 1]
                out.append((_dice(toks, joined), start, n))
        return out

    def source_of(self, texts: list[str], hint: Optional[list[int]] = None) -> Optional[str]:
        """Source for a paragraph whose earlier or current wording is in `texts`, or None when unsure.

        hint: segment positions the review source map linked to this paragraph.
        """
        for text in texts:
            exact = self.by_target.get(tm_keys.normalise_text(text))
            if exact and len(exact) == 1:
                return next(iter(exact))
        best: dict[str, float] = {}
        for text in texts:
            if source_map._w(source_map.tokens(text)) < SHORT_WEIGHT:
                continue
            for score, start, n in self._runs(text):
                positions = [self.segs[k][0] for k in range(start, start + n)]
                if hint and positions == hint:
                    score += ACCEPT - ACCEPT_WITH_MAP
                src = tm_keys.normalise_text(" ".join(self.segs[k][1] for k in range(start, start + n)))
                if src and score > best.get(src, 0.0):
                    best[src] = score
        if not best:
            return None
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        top_src, top = ranked[0]
        if top < ACCEPT:
            return None
        runner = next((s for src, s in ranked[1:] if src not in top_src and top_src not in src), 0.0)
        return top_src if top - runner >= MARGIN else None


def _map_hints(db: Session, project: TranslationProject) -> dict[str, list[int]]:
    """Paragraph -> segment indexes from the review source map, for strong text matches only."""
    from app.models.review import ReviewState

    state = db.query(ReviewState).filter(ReviewState.project_id == project.id).first()
    blocks = ((state.source_map if state else None) or {}).get("blocks") or {}
    out = {}
    for bid, entry in blocks.items():
        segs = entry.get("segments") or []
        if entry.get("via") == "segments" and (entry.get("confidence") or 0) >= source_map.STRONG_MATCH and segs:
            if segs == list(range(segs[0], segs[0] + len(segs))):
                out[bid] = segs
    return out


def _earliest_texts(db: Session, project: TranslationProject) -> dict[str, str]:
    from app.services.document_editor import _download

    row = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.project_id == project.id)
        .order_by(DocumentVersion.version.asc())
        .first()
    )
    if not row:
        return {}
    try:
        return _paragraph_texts(_download(row.s3_key))
    except Exception:
        logger.warning("Couldn't load the first document version (project=%s)", project.id)
        return {}


def approved_pairs(
    db: Session,
    project: TranslationProject,
    data: bytes,
    block_ids: Optional[set[str]] = None,
    before: Optional[dict[str, str]] = None,
) -> list[tuple[str, str]]:
    """(source, final text) for paragraphs of `data` that map confidently to source lines; skips the certification page."""
    paras = [p for p in source_map.document_paragraphs(data) if not p["cert"]]
    if block_ids is not None:
        paras = [p for p in paras if p["id"] in block_ids]
    if not paras:
        return []
    index = SegmentIndex.for_project(db, project)
    if not index.segs:
        return []
    hints = _map_hints(db, project)
    before = before or {}
    earliest: Optional[dict[str, str]] = None
    out = []
    for p in paras:
        final = p["text"]
        texts = [t for t in (before.get(p["id"]), final) if t]
        src = index.source_of(texts, hints.get(p["id"]))
        if src is None:
            if earliest is None:
                earliest = _earliest_texts(db, project)
            first = earliest.get(p["id"])
            if first and first not in texts:
                src = index.source_of([first] + texts, hints.get(p["id"]))
        if src and usable_pair(src, final):
            out.append((src, tm_keys.normalise_text(final)))
    return out


def _store(db: Session, project: TranslationProject, pairs: list[tuple[str, str]], commit: bool) -> int:
    src, tgt = tm.project_pair(project)
    if not pairs or not src or not tgt or not getattr(project, "use_tm", True):
        return 0
    return tm.upsert_entries(
        db,
        project.team_id,
        [
            {"source_language": src, "target_language": tgt, "source_text": s, "translated_text": t,
             "origin": "approved", "project_id": project.id}
            for s, t in pairs
        ],
        commit=commit,
    )


def record_edit(db: Session, project: TranslationProject, before: bytes, after: bytes) -> int:
    """Store the translator's edited paragraphs as approved; never raises and leaves committing to the caller."""
    try:
        if not tm.enabled_for(db, project):
            return 0
        old, new = _paragraph_texts(before), _paragraph_texts(after)
        changed = {bid for bid, text in new.items() if bid in old and tm_keys.normalise_text(old[bid]) != tm_keys.normalise_text(text)}
        if not changed:
            return 0
        return _store(db, project, approved_pairs(db, project, after, changed, old), commit=False)
    except Exception:
        logger.exception("Couldn't store edits in the translation memory (project=%s)", project.id)
        return 0


def record_delivery(db: Session, project: TranslationProject, data: bytes) -> int:
    """Store every confidently mapped paragraph of the delivered document as approved."""
    try:
        if not tm.enabled_for(db, project):
            return 0
        return _store(db, project, approved_pairs(db, project, data), commit=True)
    except Exception:
        logger.exception("Couldn't store the delivered document in the translation memory (project=%s)", project.id)
        db.rollback()
        return 0
