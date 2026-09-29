"""Per-team learning: document profiles, reusable templates and terminology mined from the translator's edits."""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

import anthropic
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.glossary import Glossary
from app.models.learning import DocumentTemplate, PendingLearning
from app.models.project import ProjectStatus, TranslationProject
from app.models.translation_segment import TranslationSegment
from app.services import ai_usage, claude_params, docx_blocks
from app.services.glossary_service import (
    fold_text,
    get_glossary,
    lang_key,
    language_name,
    project_source_language,
    relevant_terms,
    term_in_text,
    terminology_block,
)

logger = logging.getLogger(__name__)

QUIET_SECONDS = 30
CLAIM_TIMEOUT = timedelta(minutes=10)
PENDING_MAX_AGE = timedelta(days=2)
MIN_CONFIDENCE = 0.6
MAX_SOURCE_CONTEXT = 12_000
MAX_EDIT_CHARS = 4_000

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string"},
        "country": {"type": "string"},
        "issuing_authority": {"type": "string"},
        "source_language": {"type": "string"},
        "format_variant": {"type": "string"},
        "title": {"type": "string"},
    },
    "required": ["document_type", "country", "issuing_authority", "source_language", "format_variant", "title"],
    "additionalProperties": False,
}

_PROFILE_PROMPT = """Identify this document so a translation agency can match it with documents of the same \
kind it translated before. The same kind of document from the same issuer must get the same answers every \
time, so use the canonical forms below.

- document_type: generic English name, lowercase, e.g. "birth certificate", "residence certificate", \
"driving licence", "identity card", "passport", "marriage certificate", "criminal record certificate", \
"university diploma", "transcript of records", "payslip", "bank statement", "tax return", "invoice", \
"contract", "medical report", "letter".
- country: ISO 3166-1 alpha-2 code of the issuing country, uppercase ("" if unknown).
- issuing_authority: the top-level issuing body exactly as printed, without department or office \
(e.g. "Comune di Bari", "Motorizzazione Civile", "Università di Bologna"); "" if none.
- source_language: English name of the document's main language (e.g. "Italian").
- format_variant: a short stable label for the layout model when the document shows one (e.g. \
"EU card model 2013", "multilingual extract"); otherwise "".
- title: the document's own title as printed, in its language ("" if none)."""

_STOPWORDS = {
    "di", "de", "del", "della", "dei", "degli", "delle", "da", "do", "dos", "das", "du", "des", "of", "the",
    "la", "le", "el", "lo", "los", "las", "and", "e", "y", "et", "und", "der", "die", "das", "von", "van",
}


def slug(text: str, limit: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    words = [w for w in re.split(r"[^a-z0-9]+", ascii_text) if w and w not in _STOPWORDS]
    return "-".join(words)[:limit].strip("-")


def build_doc_key(profile: dict) -> str:
    parts = [
        slug(profile.get("document_type", "")) or "document",
        slug(profile.get("country", ""), 3) or "xx",
        slug(profile.get("issuing_authority", "")) or "any",
    ]
    variant = slug(profile.get("format_variant", ""))
    if variant:
        parts.append(variant)
    return ".".join(parts)


def _base_key(doc_key: str) -> str:
    return ".".join(doc_key.split(".")[:3])


def _first_page_block(data: bytes, file_name: str) -> Optional[dict]:
    name = (file_name or "").lower()
    png = None
    if name.endswith(".pdf"):
        import fitz

        with fitz.open(stream=data, filetype="pdf") as doc:
            if len(doc):
                png = doc[0].get_pixmap(dpi=110).tobytes("png")
    elif name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")):
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        png = buf.getvalue()
    if not png:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}}


def classify_document(data: bytes, file_name: str, text_hint: str = "") -> Optional[dict]:
    """One cheap vision call; returns the profile with its doc_key, or None."""
    key = claude_params.api_key()
    if not key:
        return None
    content: list = []
    image = _first_page_block(data, file_name)
    if image:
        content.append(image)
    if text_hint.strip():
        content.append({"type": "text", "text": f"EXTRACTED TEXT (may be partial)\n{text_hint[:3000]}"})
    if not content:
        return None
    content.append({"type": "text", "text": _PROFILE_PROMPT})
    model = claude_params.CLASSIFIER_MODEL
    resp = claude_params.create_message(
        anthropic.Anthropic(api_key=key),
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": PROFILE_SCHEMA}},
        **claude_params.request_params(model, max_tokens=400),
    )
    claude_params.log_usage("doc_profile", resp)
    if resp.stop_reason == "refusal":
        return None
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    profile = {k: str(v or "").strip() for k, v in json.loads(raw).items()}
    profile["country"] = profile.get("country", "").upper()[:2]
    profile["doc_key"] = build_doc_key(profile)
    return profile


def profile_project(db: Session, project: TranslationProject, data: bytes, text_hint: str = "") -> Optional[dict]:
    """Classify and store the profile on the project; any failure is logged and ignored."""
    try:
        with ai_usage.ai_context(action="classify", project_id=project.id, team_id=project.team_id):
            profile = classify_document(data, project.file_name or "", text_hint)
    except Exception:
        logger.exception("Document profile failed (project=%s)", project.id)
        return None
    if not profile:
        return None
    project.doc_profile = profile
    project.doc_key = profile["doc_key"]
    db.commit()
    logger.info("Document profile (project=%s): %s", project.id, profile["doc_key"])
    return profile


def ensure_profile(db: Session, project: TranslationProject) -> Optional[dict]:
    if project.doc_key:
        return project.doc_profile
    from app.services.document_editor import _download

    try:
        data = _download(project.file_path)
    except Exception:
        logger.exception("Couldn't load source for profiling (project=%s)", project.id)
        return None
    return profile_project(db, project, data, source_text_of(db, project))



def source_text_of(db: Session, project: TranslationProject) -> str:
    rows = (
        db.query(TranslationSegment.source_text)
        .filter(TranslationSegment.project_id == project.id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    return "\n".join(r.source_text or "" for r in rows)


def find_template(db: Session, team_id, doc_key: Optional[str], target_language: str) -> Optional[DocumentTemplate]:
    """Exact kind first, then the same document type and issuer in another layout variant."""
    tgt = lang_key(target_language)
    if not doc_key or not tgt:
        return None
    base = db.query(DocumentTemplate).filter(DocumentTemplate.team_id == team_id, DocumentTemplate.target_language == tgt)
    exact = base.filter(DocumentTemplate.doc_key == doc_key).first()
    if exact:
        return exact
    prefix = _base_key(doc_key)
    return (
        base.filter((DocumentTemplate.doc_key == prefix) | DocumentTemplate.doc_key.like(prefix + ".%"))
        .order_by(DocumentTemplate.updated_at.desc())
        .first()
    )


def template_title(project: TranslationProject) -> str:
    p = project.doc_profile or {}
    kind = (p.get("document_type") or "Document").strip()
    kind = kind[:1].upper() + kind[1:]
    extra = p.get("issuing_authority") or p.get("country") or ""
    return f"{kind} · {extra}" if extra else kind


def _upload(data: bytes, name: str) -> str:
    from app.services.document_editor import _upload as upload

    return upload(data, name)


def capture_template(db: Session, project: TranslationProject, user) -> Optional[DocumentTemplate]:
    """Store the project's current document as the team's template for its kind of document and target language."""
    if not project.doc_key or project.status != ProjectStatus.COMPLETED:
        return None
    from app.routers.document import _initial_builder
    from app.services import document_editor
    from app.services.s3_service import delete_objects_from_s3

    data, version = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    tgt = lang_key(project.target_language)
    template = (
        db.query(DocumentTemplate)
        .filter(
            DocumentTemplate.team_id == project.team_id,
            DocumentTemplate.doc_key == project.doc_key,
            DocumentTemplate.target_language == tgt,
        )
        .with_for_update()
        .first()
    )
    if template and template.source_project_id == project.id and template.source_version == version:
        return template
    key = _upload(data, f"template_{project.doc_key[:60]}.docx")
    now = datetime.utcnow()
    if template:
        old_key = template.s3_key
        template.s3_key = key
        template.source_project_id = project.id
        template.source_version = version
        template.source_text = source_text_of(db, project)
        template.doc_profile = project.doc_profile
        template.title = template_title(project)
        template.updated_at = now
        if old_key and old_key != key:
            try:
                delete_objects_from_s3([old_key])
            except Exception:
                logger.warning("Couldn't delete replaced template file %s", old_key)
    else:
        template = DocumentTemplate(
            team_id=project.team_id,
            doc_key=project.doc_key,
            target_language=tgt,
            title=template_title(project),
            doc_profile=project.doc_profile,
            source_project_id=project.id,
            source_version=version,
            s3_key=key,
            source_text=source_text_of(db, project),
            use_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(template)
    db.commit()
    logger.info("Template captured (team=%s key=%s project=%s)", project.team_id, project.doc_key, project.id)
    return template


def capture_template_in_background(project_id, user_id) -> None:
    from app.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        project = db.query(TranslationProject).filter(TranslationProject.id == project_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if project and user:
            capture_template(db, project, user)
    except Exception:
        db.rollback()
        logger.exception("Template capture failed (project=%s)", project_id)
    finally:
        db.close()


def mark_template_used(db: Session, project: TranslationProject, template: DocumentTemplate) -> None:
    project.template_id = template.id
    template.use_count = (template.use_count or 0) + 1
    template.last_used_at = datetime.utcnow()



def team_terms(db: Session, project: TranslationProject, source_text: str) -> list[Glossary]:
    if not getattr(project, "apply_glossary", True):
        return []
    try:
        entries = get_glossary(db, project.team_id, project_source_language(project), project.target_language)
        return relevant_terms(entries, source_text)
    except Exception:
        logger.exception("Team terminology lookup failed (project=%s)", project.id)
        return []


def team_terminology(db: Session, project: TranslationProject, source_text: Optional[str] = None) -> str:
    from app.services import batch_terms

    text = source_text if source_text is not None else source_text_of(db, project)
    blocks = [terminology_block(team_terms(db, project, text)), batch_terms.terminology_block(db, project, text or None)]
    return "\n".join(b for b in blocks if b)



def _paragraphs(data: bytes) -> dict[str, str]:
    doc = docx_blocks._Doc.load(data)
    out: dict[str, str] = {}
    for p in doc.paragraphs():
        bid = docx_blocks._block_id_of(p)
        if bid:
            out[bid] = docx_blocks.paragraph_text(p)
    return out


def _only_data_changed(before: str, after: str) -> bool:
    strip = lambda s: re.sub(r"[\W\d_]+", "", fold_text(s))
    return strip(before) == strip(after)


def paragraph_changes(before: bytes, after: bytes) -> list[tuple[Optional[str], str, str]]:
    old, new = _paragraphs(before), _paragraphs(after)
    changes = [(bid, old[bid], text) for bid, text in new.items() if bid in old and old[bid] != text]
    removed = [t for b, t in old.items() if b not in new and t.strip()]
    added = [t for b, t in new.items() if b not in old and t.strip()]
    if removed or added:
        changes.append((None, "\n".join(removed), "\n".join(added)))
    return [
        (bid, b[:MAX_EDIT_CHARS], a[:MAX_EDIT_CHARS])
        for bid, b, a in changes
        if " ".join(b.split()) != " ".join(a.split()) and not _only_data_changed(b, a)
    ]


def record_changes(db: Session, project: TranslationProject, before: bytes, after: bytes, origin: str = "typed") -> int:
    """Queue changed paragraphs for terminology mining; never raises, never calls a model."""
    try:
        changes = paragraph_changes(before, after)
        if not changes:
            return 0
        with db.begin_nested():
            for bid, b, a in changes:
                db.add(PendingLearning(project_id=project.id, block_id=bid, before_text=b, after_text=a, origin=origin))
        return len(changes)
    except Exception:
        logger.exception("Couldn't record edits for learning (project=%s)", project.id)
        return 0


TERMS_SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_term": {"type": "string"},
                    "target_term": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["source_term", "target_term", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["terms"],
    "additionalProperties": False,
}

_TERMS_PROMPT = """A professional translator corrected an AI translation from {src} into {tgt}. Find the \
TERMINOLOGY DECISIONS in these corrections: cases where the translator chose how a specific source-language \
term (an institution, office, title, legal or administrative concept, fixed phrase) is to be translated, so \
the team can reuse that choice in every future document.

Skip:
- data fixes (names, numbers, dates, codes, addresses);
- typos, punctuation and formatting;
- one-off rewordings of a sentence that don't fix how a term is translated.

For each decision give source_term exactly as it appears in the SOURCE TEXT (shortest form that carries the \
meaning, base form, no surrounding words), target_term exactly as the translator wrote it in the corrected \
text, and confidence 0-1 that this is a reusable terminology choice. Return an empty list when there is none.

SOURCE TEXT
{source}

CORRECTIONS
{changes}"""


def _collapse(rows: list[PendingLearning]) -> list[tuple[str, str]]:
    """One before/after pair per paragraph: the first before and the last after."""
    by_block: dict[str, list] = {}
    loose = []
    for r in sorted(rows, key=lambda r: r.created_at or datetime.min):
        if r.block_id:
            entry = by_block.setdefault(r.block_id, [r.before_text, r.after_text])
            entry[1] = r.after_text
        else:
            loose.append((r.before_text, r.after_text))
    pairs = [(b, a) for b, a in by_block.values() if b != a] + loose
    return [(b, a) for b, a in pairs if not _only_data_changed(b, a)]


def extract_terms(project: TranslationProject, source_text: str, pairs: list[tuple[str, str]]) -> list[dict]:
    key = claude_params.api_key()
    if not key or not pairs:
        return []
    changes = "\n\n".join(f"BEFORE: {b}\nAFTER: {a}" for b, a in pairs[:40])
    prompt = _TERMS_PROMPT.format(
        src=language_name(lang_key(project_source_language(project))) or "the source language",
        tgt=language_name(lang_key(project.target_language)),
        source=source_text[:MAX_SOURCE_CONTEXT] or "(not available)",
        changes=changes,
    )
    model = claude_params.CLASSIFIER_MODEL
    with ai_usage.ai_context(action="learning", project_id=project.id, team_id=project.team_id):
        resp = claude_params.create_message(
            anthropic.Anthropic(api_key=key),
            model=model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": TERMS_SCHEMA}},
            **claude_params.request_params(model, max_tokens=2000),
        )
    claude_params.log_usage("learn_terms", resp)
    if resp.stop_reason == "refusal":
        return []
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    return list(json.loads(raw).get("terms") or [])


def _plausible(term: dict, source_folded: str, after_folded: str) -> bool:
    src, tgt = (term.get("source_term") or "").strip(), (term.get("target_term") or "").strip()
    if not src or not tgt or len(src) > 80 or len(tgt) > 120 or len(src.split()) > 8:
        return False
    if float(term.get("confidence") or 0) < MIN_CONFIDENCE:
        return False
    if not re.search(r"[^\W\d_]", src) or fold_text(src) == fold_text(tgt):
        return False
    # The model must quote the source and the translator's text, not invent either side.
    return (not source_folded or term_in_text(src, source_folded)) and fold_text(tgt) in after_folded


def upsert_terms(db: Session, project: TranslationProject, terms: list[dict], after_text: str, source_text: str) -> list[Glossary]:
    src_key, tgt_key = lang_key(project_source_language(project)), lang_key(project.target_language)
    if not src_key or not tgt_key:
        return []
    source_folded, after_folded = fold_text(source_text), fold_text(after_text)
    existing = [
        g
        for g in db.query(Glossary).filter(Glossary.team_id == project.team_id).all()
        if lang_key(g.source_language) == src_key and lang_key(g.target_language) == tgt_key
    ]
    by_source = {fold_text(g.source_term).strip(): g for g in existing}
    saved = []
    for term in terms:
        if not _plausible(term, source_folded, after_folded):
            continue
        src, tgt = term["source_term"].strip(), term["target_term"].strip()
        conf = round(min(1.0, float(term["confidence"])), 2)
        row = by_source.get(fold_text(src))
        if row is None:
            row = Glossary(
                team_id=project.team_id,
                source_language=language_name(src_key),
                target_language=language_name(tgt_key),
                source_term=src,
                target_term=tgt,
                usage_count=1,
                origin="learned",
                confidence=conf,
                learned_from_project_id=project.id,
            )
            db.add(row)
            by_source[fold_text(src)] = row
        elif fold_text(row.target_term) == fold_text(tgt):
            if row.origin == "rejected":
                continue
            row.usage_count = (row.usage_count or 0) + 1
            row.confidence = max(row.confidence or 0, conf) if row.origin == "learned" else row.confidence
        elif row.origin == "manual":
            # A term the team typed in by hand is never overwritten by inference.
            continue
        else:
            row.target_term = tgt
            row.origin = "learned"
            row.confidence = conf
            row.usage_count = 1
            row.learned_from_project_id = project.id
        saved.append(row)
    return saved


def learn_from_rows(db: Session, project: TranslationProject, rows: list[PendingLearning]) -> list[Glossary]:
    pairs = _collapse(rows)
    if not pairs or not lang_key(project_source_language(project)):
        return []
    source_text = source_text_of(db, project)
    terms = extract_terms(project, source_text, pairs)
    saved = upsert_terms(db, project, terms, "\n".join(a for _, a in pairs), source_text)
    if saved:
        logger.info("Learned %d term(s) from edits (project=%s)", len(saved), project.id)
    return saved


def process_pending(now: Optional[datetime] = None, quiet_seconds: int = QUIET_SECONDS, max_projects: int = 10) -> int:
    """Mine terminology from projects whose last edit is at least `quiet_seconds` old. Returns projects processed."""
    from app.database import SessionLocal

    now = now or datetime.utcnow()
    db = SessionLocal()
    done = 0
    try:
        db.query(PendingLearning).filter(PendingLearning.created_at < now - PENDING_MAX_AGE).delete(synchronize_session=False)
        db.commit()
        claim_before = now - CLAIM_TIMEOUT
        ready = (
            db.query(PendingLearning.project_id)
            .group_by(PendingLearning.project_id)
            .having(func.max(PendingLearning.created_at) < now - timedelta(seconds=quiet_seconds))
            .limit(max_projects)
            .all()
        )
        for (project_id,) in ready:
            claimable = (PendingLearning.claimed_at.is_(None)) | (PendingLearning.claimed_at < claim_before)
            ids = [
                r.id
                for r in db.query(PendingLearning.id)
                .filter(PendingLearning.project_id == project_id, claimable)
                .with_for_update(skip_locked=True)
                .all()
            ]
            if not ids:
                db.commit()
                continue
            db.query(PendingLearning).filter(PendingLearning.id.in_(ids)).update(
                {PendingLearning.claimed_at: now}, synchronize_session=False
            )
            db.commit()
            try:
                project = db.query(TranslationProject).filter(TranslationProject.id == project_id).first()
                rows = db.query(PendingLearning).filter(PendingLearning.id.in_(ids)).all()
                if project:
                    learn_from_rows(db, project, rows)
                db.query(PendingLearning).filter(PendingLearning.id.in_(ids)).delete(synchronize_session=False)
                db.commit()
                done += 1
            except Exception:
                db.rollback()
                logger.exception("Learning from edits failed (project=%s); will retry", project_id)
    finally:
        db.close()
    return done
