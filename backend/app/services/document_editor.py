"""Versioned, addressable editing of a project's translated DOCX, including Claude chat edits."""
from __future__ import annotations

import base64
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

from app.models.document_version import DocumentVersion
from app.models.project import TranslationProject
from app.models.user import User
from app.services import claude_params, docx_blocks

logger = logging.getLogger(__name__)

MAX_VERSIONS = 50
MAX_FULL_XML_CHARS = 60_000

_OP_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": ["set_text", "replace_paragraph", "replace", "insert_before", "insert_after", "delete"],
                    },
                    "target": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["op", "target", "content"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reply", "operations"],
    "additionalProperties": False,
}

_SYSTEM = """You edit a translated Word document at a professional translator's request, the way a \
designer edits a layout: precisely, touching only what is asked. The attached file is the ORIGINAL \
source document; the translation you edit is in {target_lang}.

You receive an outline of the whole translation (one line per top-level block: [id] (location) \
description), the WordprocessingML of the blocks around the user's selection, the selected text, \
the conversation so far and the request.

Answer with JSON: "reply" (one or two sentences to the user, written in the same language as the \
REQUEST text, never the source document's language, saying what you changed or why you changed \
nothing) and "operations". Always use the SMALLEST operation \
that does the job; the user is waiting while you write:
- set_text: new wording for ONE paragraph (any paragraph id, including inside tables, headers and \
footers). "content" is the paragraph's complete new plain text (\\t for a tab, \\n for a line \
break). Its formatting is kept automatically. Use this for every wording, spelling, number or \
terminology change.
- replace_paragraph: restyle or restructure ONE paragraph (bold, size, alignment, splitting it). \
"content" is one or more <w:p> elements; target is the paragraph id.
- replace: swap a whole top-level block (outline id) for new <w:p>/<w:tbl> XML. Only for layout \
changes (make columns, rebuild a table, reorder), never for a wording change.
- insert_before / insert_after: add <w:p>/<w:tbl> XML next to a top-level block.
- delete: remove a top-level block ("content": "").

Rules:
- XML uses the w: prefix (already declared). Top level may only be <w:p> or <w:tbl>. No hyperlinks \
or <w:sectPr>. Never create images; an existing <w:drawing> (picture, stamp, logo) may only be kept \
or moved by copying it unchanged, including its r:embed id. Keep <w:sdt> content controls \
(certification fields) and edit only the text inside them.
- Change only what the request asks. Keep every other character, number, name and formatting \
exactly as it is, and keep the <w:bookmarkStart w:name="_b..."/>/<w:bookmarkEnd/> pair of each \
paragraph you keep. New paragraphs don't need bookmarks.
- To move content: delete it where it was and insert it where it belongs, in one response.
- For a vague request ("find a better alternative"), make the change directly and name it in the \
reply; don't ask for confirmation.
- Side-by-side layout = a table with all w:tblBorders set to w:val="nil".
- The translation must stay faithful to the source. If a request would add, drop or alter meaning \
compared with the source, do it only if the user is explicit, and say so in the reply.
- If the request is a question, answer it in "reply" with no operations.
- Non-text elements and unreadable content follow these rules:
{notation_rules}"""


class ChatEditError(RuntimeError):
    def __init__(self, message: str, technical: str = ""):
        super().__init__(message)
        self.technical = technical


def _download(key: str) -> bytes:
    from app.services.s3_service import download_file_from_s3

    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / "file"
        download_file_from_s3(key, path)
        return path.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _upload(data: bytes, name: str) -> str:
    from app.services.s3_service import upload_file_to_s3

    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / name
        path.write_bytes(data)
        return upload_file_to_s3(path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def save_version(db: Session, project: TranslationProject, data: bytes, note: str, user: Optional[User]) -> int:
    """Store `data` as the next version and make it current. Caller commits."""
    key = _upload(data, f"document_{project.id}.docx")
    project.document_version = (project.document_version or 0) + 1
    db.add(DocumentVersion(
        project_id=project.id,
        version=project.document_version,
        s3_key=key,
        note=note[:200] if note else None,
        created_by=user.id if user else None,
    ))
    project.authored_docx_s3_key = key
    project.edited_html = None
    _prune(db, project)
    return project.document_version


def _prune(db: Session, project: TranslationProject) -> None:
    from app.services.s3_service import delete_objects_from_s3

    old = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.project_id == project.id,
            DocumentVersion.version <= project.document_version - MAX_VERSIONS,
        )
        .all()
    )
    if old:
        delete_objects_from_s3([v.s3_key for v in old])
        for v in old:
            db.delete(v)


def current_document(db: Session, project: TranslationProject, user: User, build_initial) -> tuple[bytes, int]:
    """Current tagged DOCX and its version; the first call snapshots the pipeline output as version 1."""
    if project.document_version:
        row = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.project_id == project.id, DocumentVersion.version == project.document_version)
            .first()
        )
        if row:
            return _download(row.s3_key), project.document_version
    data = docx_blocks.tag_blocks(build_initial())
    version = save_version(db, project, data, "Initial translation", user)
    db.commit()
    return data, version


def undo(db: Session, project: TranslationProject) -> int:
    from app.services.s3_service import delete_objects_from_s3

    rows = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.project_id == project.id)
        .order_by(DocumentVersion.version.desc())
        .limit(2)
        .all()
    )
    if len(rows) < 2:
        return 0
    current, previous = rows
    delete_objects_from_s3([current.s3_key])
    db.delete(current)
    project.document_version = previous.version
    project.authored_docx_s3_key = previous.s3_key
    project.edited_html = None
    return previous.version


def _source_block(project: TranslationProject) -> Optional[dict]:
    name = (project.file_name or "").lower()
    try:
        data = _download(project.file_path)
    except Exception:
        logger.exception("Couldn't load source for chat edit (project=%s)", project.id)
        return None
    cache = {"type": "ephemeral", "ttl": "1h"}
    if name.endswith(".pdf"):
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(data).decode()},
            "cache_control": cache,
        }
    for ext, media in ((".png", "image/png"), (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".webp", "image/webp")):
        if name.endswith(ext):
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()},
                "cache_control": cache,
            }
    if name.endswith(".docx"):
        import io

        from docx import Document

        text = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
        return {"type": "text", "text": f"ORIGINAL SOURCE TEXT\n{text}", "cache_control": cache}
    return None


def _team_terminology(project: TranslationProject) -> str:
    from sqlalchemy.orm import object_session

    from app.services.learning import team_terminology

    db = object_session(project)
    if db is None:
        return ""
    try:
        return team_terminology(db, project)
    except Exception:
        logger.exception("Terminology lookup for chat edit failed (project=%s)", project.id)
        return ""


def _request_text(data: bytes, block_ids: list[str], selected_text: str, message: str, history: list[dict]) -> str:
    outline = docx_blocks.outline(data)
    if block_ids:
        _, xml = docx_blocks.units_for_blocks(data, block_ids, neighbours=1)
        heading = "BLOCKS AROUND THE SELECTION"
    else:
        all_ids = docx_blocks.block_ids(data)
        _, xml = docx_blocks.units_for_blocks(data, all_ids, neighbours=0)
        if sum(len(x) for x in xml.values()) > MAX_FULL_XML_CHARS:
            xml = {}
        heading = "ALL BLOCKS" if xml else "BLOCK XML (omitted: document too large; ask the user to select the part to change)"
    blocks = "\n".join(f"--- [{uid}]\n{x}" for uid, x in xml.items())
    selected = docx_blocks.paragraph_texts(data, block_ids)
    selected_list = "\n".join(f"[{bid}] {text}" for bid, text in selected.items()) or "(none)"
    convo = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in history[-10:]) or "(none)"
    return (
        f"OUTLINE OF THE TRANSLATION\n{outline}\n\n"
        f"SELECTED PARAGRAPHS (targets for set_text / replace_paragraph)\n{selected_list}\n\n"
        f"{heading}\n{blocks}\n\n"
        f"SELECTED TEXT\n{selected_text or '(no selection: the request is about the whole document)'}\n\n"
        f"CONVERSATION SO FAR\n{convo}\n\n"
        f"REQUEST\n{message}\n\n"
        "Write \"reply\" in the language this REQUEST is written in (English if unclear)."
    )


def chat_edit(
    project: TranslationProject,
    data: bytes,
    block_ids: list[str],
    selected_text: str,
    message: str,
    history: list[dict],
) -> tuple[bytes, str, list[str]]:
    """Ask Claude for operations, apply them, retry once with the error if they don't apply."""
    from app.services.claude_authored_rebuild import NOTATION_RULES
    from app.services.project_instructions import prompt_block

    key = claude_params.api_key()
    if not key:
        raise ChatEditError("The AI assistant is not configured")
    client = anthropic.Anthropic(api_key=key)
    model = claude_params.rebuild_model()
    system = _SYSTEM.format(target_lang=project.target_language or "the target language", notation_rules=NOTATION_RULES)

    content = []
    source = _source_block(project)
    if source:
        content.append(source)
    terminology = _team_terminology(project)
    if terminology:
        content.append({"type": "text", "text": terminology})
    instructions = prompt_block(project.ai_instructions)
    if instructions:
        content.append({"type": "text", "text": instructions})
    content.append({"type": "text", "text": _request_text(data, block_ids, selected_text, message, history)})
    messages = [{"role": "user", "content": content}]

    # Low effort: edits are local and the user is waiting; output length is most of the latency.
    params = claude_params.request_params(model, max_tokens=16000, thinking=True, effort="low")
    output_config = {**params.pop("output_config", {}), "format": {"type": "json_schema", "schema": _OP_SCHEMA}}

    last_error = None
    for attempt in range(2):
        try:
            resp = claude_params.create_message(
                client,
                model=model,
                max_tokens=16000,
                system=system,
                messages=messages,
                output_config=output_config,
                **params,
            )
        except anthropic.APIError as e:
            logger.exception("Chat edit call failed (project=%s)", project.id)
            status = getattr(e, "status_code", "")
            raise ChatEditError(
                "The assistant couldn't process the request; try again",
                technical=f"{type(e).__name__} {status}: {getattr(e, 'message', str(e))}"[:500],
            ) from e
        claude_params.log_usage("doc_chat", resp)
        if resp.stop_reason == "refusal":
            raise ChatEditError("The assistant declined this request")
        raw = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ChatEditError("The assistant returned an unreadable answer; try again") from e
        operations = result.get("operations") or []
        if not operations:
            return data, result.get("reply", ""), []
        try:
            new_data, changed = docx_blocks.apply_operations(data, operations)
            return new_data, result.get("reply", ""), changed
        except docx_blocks.DocxEditError as e:
            last_error = str(e)
            logger.warning("Chat edit operations rejected (attempt %d): %s", attempt + 1, e)
            messages = messages + [
                {"role": "assistant", "content": resp.content},
                {"role": "user", "content": f"Those operations could not be applied: {e}. Return corrected JSON."},
            ]
    raise ChatEditError(f"The edit couldn't be applied ({last_error}); try rephrasing")
