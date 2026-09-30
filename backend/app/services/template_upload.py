"""Templates from a past job: the original document plus the translator's finished translation of it."""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

from app.models.learning import DocumentTemplate, TemplateUpload
from app.services import ai_usage, claude_params, docx_blocks, learning, source_map, tm_capture, tm_keys
from app.services import translation_memory_service as tm
from app.services.glossary_service import lang_key, language_name

logger = logging.getLogger(__name__)

MAX_BYTES = 20 * 1024 * 1024
ORIGINAL_EXTS = (".pdf", ".jpg", ".jpeg", ".png")
TRANSLATION_EXTS = (".docx",)
PENDING_TTL = timedelta(hours=24)
STORAGE_PREFIX = "pending-templates"
PROFILE_FIELDS = ("document_type", "country", "issuing_authority", "format_variant", "source_language")
MAX_ALIGN_LINES = 400
MAX_ALIGN_PARAGRAPHS = 400
MAX_ALIGN_TEXT = 400
MAX_LINES_PER_PARAGRAPH = tm.MAX_WINDOW
ALIGN_MAX_TOKENS = 8000


class UploadError(ValueError):
    pass


def _ext(name: str) -> str:
    return os.path.splitext(name or "")[1].lower()


def check_original(name: str, data: bytes) -> None:
    if _ext(name) not in ORIGINAL_EXTS:
        raise UploadError("The original document must be a PDF, JPG or PNG file")
    if not data:
        raise UploadError("The original document is empty")
    if len(data) > MAX_BYTES:
        raise UploadError("The original document is larger than 20 MB")


def check_translation(name: str, data: bytes) -> None:
    if _ext(name) not in TRANSLATION_EXTS:
        raise UploadError("Your translation must be a Word .docx file")
    if not data:
        raise UploadError("Your translation is empty")
    if len(data) > MAX_BYTES:
        raise UploadError("Your translation is larger than 20 MB")
    try:
        from docx import Document

        Document(io.BytesIO(data))
        doc = docx_blocks._Doc.load(data)
    except Exception:
        raise UploadError("Your translation couldn't be opened as a Word document")
    if not any(docx_blocks.paragraph_text(p).strip() for p in doc.paragraphs()):
        raise UploadError("Your translation has no text")


def extract_source_lines(data: bytes, file_name: str) -> list[str]:
    """Text lines of the original in reading order; images are read with OCR."""
    from app.services.layout_translator import extract_segments

    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / f"original{_ext(file_name)}"
        path.write_bytes(data)
        _, segments = extract_segments(str(path))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return [t for t in (tm_keys.normalise_text(s.text) for s in segments) if t]


def _store(data: bytes, name: str) -> str:
    from app.services.s3_service import upload_file_to_s3

    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / (re.sub(r"[^\w.\-]+", "_", name)[-80:] or "file")
        path.write_bytes(data)
        return upload_file_to_s3(path, prefix=STORAGE_PREFIX)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _delete_files(keys: list[str]) -> None:
    from app.services.s3_service import delete_objects_from_s3

    try:
        delete_objects_from_s3([k for k in keys if k])
    except Exception:
        logger.warning("Couldn't delete pending template files %s", keys)


def clean_profile(fields: dict) -> dict:
    profile = {k: " ".join(str(fields.get(k) or "").split())[:120] for k in PROFILE_FIELDS}
    profile["document_type"] = profile["document_type"].lower()
    profile["country"] = profile["country"].upper()[:2]
    profile["title"] = str(fields.get("title") or "")[:200]
    profile["doc_key"] = learning.build_doc_key(profile)
    return profile


def existing_template(db: Session, team_id, doc_key: str, target_language: str) -> Optional[DocumentTemplate]:
    return (
        db.query(DocumentTemplate)
        .filter(
            DocumentTemplate.team_id == team_id,
            DocumentTemplate.doc_key == doc_key,
            DocumentTemplate.target_language == lang_key(target_language),
        )
        .first()
    )


def analyze(
    db: Session,
    team_id,
    user_id,
    original_name: str,
    original: bytes,
    translation_name: str,
    translation: bytes,
    target_language: str,
) -> TemplateUpload:
    """Validate and store both files, read and classify the original. Raises UploadError."""
    if not lang_key(target_language):
        raise UploadError("Choose the language of your translation")
    check_original(original_name, original)
    check_translation(translation_name, translation)
    keys = [_store(original, original_name), _store(translation, translation_name)]
    try:
        with ai_usage.ai_context(action="template_upload", team_id=team_id, user_id=user_id):
            try:
                lines = extract_source_lines(original, original_name)
            except Exception:
                logger.exception("Couldn't read the original of a template upload (team=%s)", team_id)
                lines = []
            if not lines:
                raise UploadError("Couldn't read any text in the original document")
            try:
                found = learning.classify_document(original, original_name, "\n".join(lines))
            except Exception:
                logger.exception("Document profile failed for a template upload (team=%s)", team_id)
                found = None
        now = datetime.utcnow()
        row = TemplateUpload(
            team_id=team_id,
            user_id=user_id,
            original_name=original_name[:255],
            original_key=keys[0],
            translation_key=keys[1],
            target_language=target_language,
            profile=clean_profile(found or {}),
            source_lines=lines,
            created_at=now,
            expires_at=now + PENDING_TTL,
        )
        db.add(row)
        db.commit()
        return row
    except Exception:
        db.rollback()
        _delete_files(keys)
        raise


def pending_for(db: Session, upload_id, team_ids, lock: bool = False) -> Optional[TemplateUpload]:
    q = db.query(TemplateUpload).filter(TemplateUpload.id == upload_id, TemplateUpload.team_id.in_(team_ids))
    if lock:
        q = q.with_for_update()
    return q.first()


def is_expired(row: TemplateUpload, now: Optional[datetime] = None) -> bool:
    return row.expires_at <= (now or datetime.utcnow())


def save_template(
    db: Session, row: TemplateUpload, fields: dict, target_language: str
) -> tuple[DocumentTemplate, bool, dict, bytes]:
    """Store the translation with block ids as the team's template and drop the pending upload."""
    from app.services.document_editor import _download

    profile = clean_profile({**(row.profile or {}), **fields})
    if not profile["document_type"]:
        raise UploadError("Enter the document type")
    if not lang_key(target_language):
        raise UploadError("Choose the language of your translation")
    data = docx_blocks.tag_blocks(_download(row.translation_key))
    template, replaced = learning.store_template(
        db, row.team_id, profile["doc_key"], target_language, profile, data, "\n".join(row.source_lines or []),
    )
    keys = [row.original_key, row.translation_key]
    db.delete(row)
    db.commit()
    _delete_files(keys)
    return template, replaced, profile, data


ALIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "pairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paragraph_id": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["paragraph_id", "lines"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["pairs"],
    "additionalProperties": False,
}

ALIGN_PROMPT = """A professional translator translated a document from {src} into {tgt}. Match each paragraph \
of the translation with the source lines it translates, so the pairs can be stored in the translator's \
translation memory.

SOURCE LINES are the original document's text lines in reading order, each with a number. TRANSLATION \
PARAGRAPHS are the paragraphs of the translator's Word file, each with an id.

For every translation paragraph that translates specific source lines, return its id and the numbers of \
those lines:
- consecutive lines only, in order, at most {max_lines} per paragraph;
- the paragraph must translate exactly those lines: nothing missing, nothing added;
- each source line belongs to one paragraph at most;
- leave out translator's notes, bracketed notations such as [stamp] or [signature], text the translator \
added, and the translator's certification or declaration;
- leave out anything you are unsure about: a missing pair is better than a wrong one.

SOURCE LINES
{lines}

TRANSLATION PARAGRAPHS
{paragraphs}"""


def _clip(text: str) -> str:
    return text if len(text) <= MAX_ALIGN_TEXT else text[:MAX_ALIGN_TEXT] + "…"


def alignable_paragraphs(data: bytes) -> list[dict]:
    """Translation paragraphs worth aligning: no certification page, no notation-only or letterless text."""
    out = []
    for p in source_map.document_paragraphs(data):
        text = tm_keys.normalise_text(p["text"])
        if p["cert"] or not text or tm_capture._NOTATION_ONLY.match(text) or not any(c.isalpha() for c in text):
            continue
        out.append({"id": p["id"], "text": text})
    return out[:MAX_ALIGN_PARAGRAPHS]


def request_alignment(lines: list[str], paragraphs: list[dict], src: str, tgt: str) -> list[dict]:
    """One structured call on the classifier model; returns the raw pairs."""
    key = claude_params.api_key()
    if not key:
        return []
    prompt = ALIGN_PROMPT.format(
        src=language_name(src) or "the source language",
        tgt=language_name(lang_key(tgt)) or tgt,
        max_lines=MAX_LINES_PER_PARAGRAPH,
        lines="\n".join(f"[{i}] {_clip(t)}" for i, t in enumerate(lines)),
        paragraphs="\n".join(f"{p['id']}: {_clip(p['text'])}" for p in paragraphs),
    )
    model = claude_params.CLASSIFIER_MODEL
    resp = claude_params.create_message(
        anthropic.Anthropic(api_key=key),
        model=model,
        max_tokens=ALIGN_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": ALIGN_SCHEMA}},
        **claude_params.request_params(model, max_tokens=ALIGN_MAX_TOKENS),
    )
    claude_params.log_usage("template_upload_align", resp)
    if resp.stop_reason in ("refusal", "max_tokens"):
        return []
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    return list(json.loads(raw).get("pairs") or [])


def checked_pairs(raw: list[dict], lines: list[str], paragraphs: list[dict]) -> list[tuple[str, str]]:
    """(source, translation) for pairs that are well formed and pass the memory's quality checks."""
    texts = {p["id"]: p["text"] for p in paragraphs}
    used_lines: set[int] = set()
    used_paras: set[str] = set()
    out = []
    for pair in raw:
        pid = pair.get("paragraph_id")
        idx = pair.get("lines") or []
        if pid not in texts or pid in used_paras or not idx or len(idx) > MAX_LINES_PER_PARAGRAPH:
            continue
        if not all(isinstance(i, int) and 0 <= i < len(lines) for i in idx):
            continue
        if idx != list(range(idx[0], idx[0] + len(idx))) or used_lines & set(idx):
            continue
        source = tm_keys.normalise_text(" ".join(lines[i] for i in idx))
        target = texts[pid]
        if not tm_capture.usable_pair(source, target):
            continue
        used_lines.update(idx)
        used_paras.add(pid)
        out.append((source, target))
    return out


def align_memory(db: Session, team_id, user_id, lines: list[str], data: bytes, source_language: str, target_language: str) -> int:
    """Store the aligned pairs as approved translations; never raises, returns the lines written."""
    src, tgt = tm_keys.source_lang(source_language), tm_keys.target_lang(target_language)
    if not src or not tgt or not lines:
        return 0
    try:
        paragraphs = alignable_paragraphs(data)
        if not paragraphs:
            return 0
        lines = lines[:MAX_ALIGN_LINES]
        with ai_usage.ai_context(action="template_upload", team_id=team_id, user_id=user_id):
            raw = request_alignment(lines, paragraphs, src, tgt)
        pairs = checked_pairs(raw, lines, paragraphs)
        logger.info("Template upload alignment (team=%s): %d proposed, %d kept", team_id, len(raw), len(pairs))
        if not pairs:
            return 0
        return tm.upsert_entries(
            db,
            team_id,
            [
                {"source_language": src, "target_language": tgt, "source_text": s, "translated_text": t,
                 "origin": "approved", "project_id": None}
                for s, t in pairs
            ],
        )
    except Exception:
        db.rollback()
        logger.exception("Template upload alignment failed (team=%s)", team_id)
        return 0


def purge_expired(now: Optional[datetime] = None) -> int:
    """Delete pending uploads older than a day and their files."""
    from app.database import SessionLocal

    now = now or datetime.utcnow()
    db = SessionLocal()
    try:
        rows = db.query(TemplateUpload).filter(TemplateUpload.expires_at <= now).limit(200).all()
        keys = [k for r in rows for k in (r.original_key, r.translation_key)]
        for r in rows:
            db.delete(r)
        db.commit()
        if keys:
            _delete_files(keys)
        return len(rows)
    except Exception:
        db.rollback()
        logger.exception("Couldn't purge expired template uploads")
        return 0
    finally:
        db.close()
