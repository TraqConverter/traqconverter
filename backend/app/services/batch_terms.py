"""Names and terms a client's batch settled on, reused in every other document of the batch."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

import anthropic
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.batch import Batch, BatchTerm
from app.models.project import TranslationProject
from app.services import claude_params
from app.services.glossary_service import fold_text, lang_key, language_name, project_source_language, term_in_text

logger = logging.getLogger(__name__)

KINDS = ("person", "institution", "place", "degree", "term")
MAX_INPUT_CHARS = 24_000
MAX_TERMS_PER_DOC = 40
MAX_PROMPT_TERMS = 80
HEADING = "TERMS ALREADY USED IN THIS CLIENT'S OTHER DOCUMENTS — use exactly:"

SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_term": {"type": "string"},
                    "target_term": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                },
                "required": ["source_term", "target_term", "kind"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["terms"],
    "additionalProperties": False,
}

_PROMPT = """A translator is translating a set of documents for one client from {src} into {tgt} (e.g. a \
birth certificate, a diploma, transcripts, an ID card). Every document must render the same names and terms \
the same way. Below is one finished document as SOURCE / TRANSLATION pairs.

List the renderings chosen in this document that the client's other documents must repeat exactly:
- person: people's names as written in the translation, including any transliteration or spelling choice;
- institution: universities, schools, registries, offices, courts, companies;
- place: cities, regions, countries, addresses' place names when translated or transliterated;
- degree: degree, qualification and course titles;
- term: recurring official or administrative terms (document titles, grades, legal statuses).

Skip dates, numbers, codes, generic words and whole sentences. source_term must be copied exactly from a \
SOURCE line (shortest form that identifies it); target_term exactly from the matching TRANSLATION line. \
At most {limit} items, most important first. Return an empty list when there is nothing to keep consistent.

{pairs}"""


def _pairs_text(pairs: list[tuple[str, str]]) -> str:
    out, size = [], 0
    for src, tgt in pairs:
        src, tgt = (src or "").strip(), (tgt or "").strip()
        if not src or not tgt:
            continue
        chunk = f"SOURCE: {src}\nTRANSLATION: {tgt}"
        size += len(chunk)
        if size > MAX_INPUT_CHARS:
            break
        out.append(chunk)
    return "\n\n".join(out)


def extract_terms(project: TranslationProject, pairs: list[tuple[str, str]]) -> list[dict]:
    key = claude_params.api_key()
    body = _pairs_text(pairs)
    if not key or not body:
        return []
    prompt = _PROMPT.format(
        src=language_name(lang_key(project_source_language(project))) or "the source language",
        tgt=language_name(lang_key(project.target_language)) or project.target_language,
        limit=MAX_TERMS_PER_DOC,
        pairs=body,
    )
    model = claude_params.CLASSIFIER_MODEL
    resp = claude_params.create_message(
        anthropic.Anthropic(api_key=key),
        model=model,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        **claude_params.request_params(model, max_tokens=3000),
    )
    claude_params.log_usage("batch_terms", resp)
    if resp.stop_reason in ("refusal", "max_tokens"):
        return []
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    return list(json.loads(raw).get("terms") or [])


def _valid(term: dict, source_folded: str, target_folded: str) -> bool:
    src, tgt = (term.get("source_term") or "").strip(), (term.get("target_term") or "").strip()
    if not src or not tgt or len(src) > 120 or len(tgt) > 160 or len(src.split()) > 12:
        return False
    if not any(ch.isalpha() for ch in src):
        return False
    # Both sides must be quoted from the document, never invented.
    return term_in_text(src, source_folded) and fold_text(tgt) in target_folded


def store_terms(db: Session, project: TranslationProject, terms: list[dict], pairs: list[tuple[str, str]]) -> int:
    source_folded = fold_text("\n".join(s or "" for s, _ in pairs))
    target_folded = fold_text("\n".join(t or "" for _, t in pairs))
    tgt_lang = lang_key(project.target_language) or (project.target_language or "")
    rows, seen = [], set()
    for term in terms[:MAX_TERMS_PER_DOC]:
        if not _valid(term, source_folded, target_folded):
            continue
        key = " ".join(fold_text(term["source_term"]).split())
        if key in seen:
            continue
        seen.add(key)
        kind = term.get("kind") if term.get("kind") in KINDS else "term"
        rows.append({
            "id": uuid.uuid4(),
            "batch_id": project.batch_id,
            "target_language": tgt_lang,
            "source_term": term["source_term"].strip(),
            "source_key": key,
            "target_term": term["target_term"].strip(),
            "kind": kind,
            "first_project_id": project.id,
            "created_at": datetime.utcnow(),
        })
    if not rows:
        return 0
    # First rendering wins: later documents were told to follow it.
    stmt = insert(BatchTerm).values(rows).on_conflict_do_nothing(constraint="uq_batch_term")
    return db.execute(stmt).rowcount or 0


def record_from_segments(db: Session, project: TranslationProject, pairs: list[tuple[str, str]]) -> int:
    """Extract and store this document's terms, then open the batch to parallel processing; never raises."""
    if not project.batch_id:
        return 0
    stored = 0
    try:
        terms = extract_terms(project, pairs)
        stored = store_terms(db, project, terms, pairs)
        db.commit()
        logger.info("Batch terms: %d new from project %s (batch=%s)", stored, project.id, project.batch_id)
    except Exception:
        db.rollback()
        logger.exception("Batch term extraction failed (project=%s)", project.id)
    try:
        db.query(Batch).filter(Batch.id == project.batch_id, Batch.terms_ready_at.is_(None)).update(
            {Batch.terms_ready_at: datetime.utcnow()}, synchronize_session=False
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Couldn't mark batch terms ready (batch=%s)", project.batch_id)
    return stored


def _mentioned(term: BatchTerm, folded: str) -> bool:
    if term_in_text(term.source_term, folded):
        return True
    # Names often appear reordered or in capitals ("ROSSI Mario" / "Mario Rossi").
    words = [w for w in fold_text(term.source_term).split() if len(w) > 1]
    return term.kind == "person" and bool(words) and all(term_in_text(w, folded) for w in words)


def terms_for(db: Session, project: TranslationProject, text: Optional[str] = None) -> list[BatchTerm]:
    if not getattr(project, "batch_id", None):
        return []
    tgt_lang = lang_key(project.target_language) or (project.target_language or "")
    rows = (
        db.query(BatchTerm)
        .filter(BatchTerm.batch_id == project.batch_id, BatchTerm.target_language == tgt_lang)
        .order_by(BatchTerm.created_at)
        .all()
    )
    rows = [r for r in rows if r.first_project_id != project.id]
    if text is not None:
        folded = fold_text(text)
        rows = [r for r in rows if _mentioned(r, folded)]
    return rows[:MAX_PROMPT_TERMS]


def terminology_block(db: Session, project: TranslationProject, text: Optional[str] = None) -> str:
    try:
        rows = terms_for(db, project, text)
    except Exception:
        logger.exception("Batch terms lookup failed (project=%s)", getattr(project, "id", None))
        return ""
    if not rows:
        return ""
    lines = "\n".join(f"- {r.source_term} → {r.target_term}" for r in rows)
    return f"{HEADING}\n{lines}\n"
