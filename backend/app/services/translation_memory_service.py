"""Translation memory reads and writes. Writes are best-effort and never raise."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.translation_memory import TranslationMemory
from app.services import tm_keys

logger = logging.getLogger(__name__)

_TM_MAX_SOURCE_LEN = tm_keys.MAX_SOURCE_CHARS
MAX_WINDOW = 4
PROMPT_MAX_ENTRIES = 150
PROMPT_MAX_CHARS = 12_000
PROMPT_HEADING = (
    "APPROVED TRANSLATIONS FROM THE TRANSLATOR'S MEMORY — reuse these exactly when the same source sentence appears"
)
_KEY = ("team_id", "source_language", "target_language", "source_hash")


def enabled_for(db: Session, project) -> bool:
    """The project's team plan includes the memory and it's a translation; resolved once per project object."""
    from app.dependencies.feature_guard import project_has_feature
    from app.models.project import is_dtp

    return not is_dtp(project) and project_has_feature(db, project, "terminology_memory")


def project_pair(project) -> tuple[str, str]:
    """(source, target) BCP-47 codes for a project; source is '' while the language is unknown."""
    from app.services.glossary_service import project_source_language

    return tm_keys.source_lang(project_source_language(project)), tm_keys.target_lang(getattr(project, "target_language", ""))


def _row(team_id, source_language, target_language, source_text, translated_text, origin, project_id, now) -> Optional[dict]:
    src, tgt = tm_keys.source_lang(source_language), tm_keys.target_lang(target_language)
    source_text, translated_text = (source_text or "").strip(), (translated_text or "").strip()
    if not src or not tgt or not source_text or not translated_text or len(source_text) > _TM_MAX_SOURCE_LEN:
        return None
    return {
        "team_id": team_id,
        "source_language": src,
        "target_language": tgt,
        "source_text": source_text,
        "translated_text": translated_text,
        "source_hash": tm_keys.source_hash(source_text),
        "origin": origin if origin in tm_keys.ORIGINS else "machine",
        "project_id": project_id,
        "created_at": now,
        "updated_at": now,
    }


def upsert_entries(db: Session, team_id, entries: Iterable[dict], *, commit: bool = True) -> int:
    """Insert or update entries; a machine write never replaces an approved, manual or imported one.

    Each entry: source_language, target_language, source_text, translated_text, origin, project_id (optional).
    Runs in a savepoint so a failure leaves the caller's transaction usable. Returns the rows written.
    """
    now = datetime.utcnow()
    rows: dict[tuple, dict] = {}
    for e in entries:
        row = _row(
            team_id, e.get("source_language"), e.get("target_language"), e.get("source_text"),
            e.get("translated_text"), e.get("origin", "machine"), e.get("project_id"), now,
        )
        if row is None:
            continue
        key = tuple(row[k] for k in _KEY)
        held = rows.get(key)
        if held is None or tm_keys.origin_rank(row["origin"]) >= tm_keys.origin_rank(held["origin"]):
            rows[key] = row
    if not rows:
        return 0
    stmt = insert(TranslationMemory).values(list(rows.values()))
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=list(_KEY),
        set_={
            "source_text": ex.source_text,
            "translated_text": ex.translated_text,
            "origin": ex.origin,
            "project_id": func.coalesce(ex.project_id, TranslationMemory.project_id),
            "updated_at": ex.updated_at,
        },
        where=or_(ex.origin != "machine", TranslationMemory.origin == "machine"),
    )
    try:
        with db.begin_nested():
            result = db.execute(stmt)
    except Exception:
        logger.exception("Translation memory write skipped (team=%s, %d rows)", team_id, len(rows))
        return 0
    if commit:
        try:
            db.commit()
        except Exception:
            logger.exception("Translation memory commit failed (team=%s)", team_id)
            db.rollback()
            return 0
    return max(result.rowcount or 0, 0)


def store_tm_entry(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_text: str,
    translated_text: str,
    origin: str = "machine",
    project_id=None,
    commit: bool = True,
) -> int:
    return upsert_entries(
        db,
        team_id,
        [{
            "source_language": source_language,
            "target_language": target_language,
            "source_text": source_text,
            "translated_text": translated_text,
            "origin": origin,
            "project_id": project_id,
        }],
        commit=commit,
    )


def lookup(
    db: Session,
    team_id,
    source_language: str,
    target_language: str,
    source_texts: Iterable[str],
    origins: Optional[Iterable[str]] = None,
) -> dict[str, TranslationMemory]:
    """Best entry per source hash: the exact target first, then the same language in another region."""
    src, tgt = tm_keys.source_lang(source_language), tm_keys.target_lang(target_language)
    hashes = list({tm_keys.source_hash(t) for t in source_texts if (t or "").strip()})
    if not src or not tgt or not hashes:
        return {}
    fam = tm_keys.family(tgt)
    base = tgt.split("-")[0]
    found: dict[str, TranslationMemory] = {}
    for i in range(0, len(hashes), 1000):
        q = db.query(TranslationMemory).filter(
            TranslationMemory.team_id == team_id,
            TranslationMemory.source_language == src,
            TranslationMemory.source_hash.in_(hashes[i:i + 1000]),
            or_(TranslationMemory.target_language == base, TranslationMemory.target_language.like(base + "-%")),
        )
        if origins:
            q = q.filter(TranslationMemory.origin.in_(list(origins)))
        for row in q.all():
            if tm_keys.family(row.target_language) != fam:
                continue
            held = found.get(row.source_hash)
            if held is None or _preference(row, tgt) > _preference(held, tgt):
                found[row.source_hash] = row
    return found


def _preference(row: TranslationMemory, tgt: str) -> tuple:
    return (row.target_language == tgt, tm_keys.origin_rank(row.origin), row.updated_at or datetime.min)


def exact_map(db: Session, project, source_texts: list[str]) -> dict[str, str]:
    """Normalised source text -> stored translation, for the segment fast path."""
    if not enabled_for(db, project):
        return {}
    src, tgt = project_pair(project)
    found = lookup(db, project.team_id, src, tgt, source_texts)
    return {tm_keys.normalise_text(r.source_text): r.translated_text for r in found.values()}


def _windows(lines: list[str]) -> list[str]:
    lines = [tm_keys.normalise_text(t) for t in lines]
    lines = [t for t in lines if t]
    out = []
    for i in range(len(lines)):
        for n in range(1, MAX_WINDOW + 1):
            if i + n <= len(lines):
                out.append(" ".join(lines[i:i + n]))
    return out


def prompt_block(db: Session, project, source_text: str) -> str:
    """Approved, manual and imported translations whose source appears in this document, for the rebuild prompts."""
    if not getattr(project, "use_tm", True) or not (source_text or "").strip() or not enabled_for(db, project):
        return ""
    try:
        src, tgt = project_pair(project)
        found = lookup(db, project.team_id, src, tgt, _windows(source_text.split("\n")), origins=("approved", "manual", "import"))
    except Exception:
        logger.exception("Translation memory lookup for the prompt failed (project=%s)", getattr(project, "id", None))
        return ""
    order = {"manual": 0, "approved": 1, "import": 2}
    rows = sorted(found.values(), key=lambda r: (order.get(r.origin, 3), -len(r.source_text)))
    lines, used = [], len(PROMPT_HEADING) + 1
    for r in rows:
        if len(lines) >= PROMPT_MAX_ENTRIES:
            break
        entry = f"- SOURCE: {tm_keys.normalise_text(r.source_text)}\n  TRANSLATION: {tm_keys.normalise_text(r.translated_text)}"
        if used + len(entry) + 1 > PROMPT_MAX_CHARS:
            continue
        lines.append(entry)
        used += len(entry) + 1
    if not lines:
        return ""
    return PROMPT_HEADING + "\n" + "\n".join(lines) + "\n"


def with_memory(db: Session, project, terminology: str, source_text: str) -> str:
    block = prompt_block(db, project, source_text)
    return "\n".join(b for b in (terminology, block) if b)
