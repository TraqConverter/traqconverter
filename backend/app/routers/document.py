"""Editable translated document: typed paragraph edits, Claude chat edits and undo."""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.rate_limit import user_rate_limit
from app.dependencies.tenant import get_user_project_or_404
from app.models.project import TranslationProject
from app.models.translation_segment import TranslationSegment
from app.models.user import User
from app.services import ai_allowance, ai_usage, docx_blocks, document_editor, learning

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Document"])

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class _TextEdit(BaseModel):
    block_id: str = Field(pattern=r"^_b[0-9a-f]{8}$")
    text: str = Field(max_length=20_000)


class _EditsPayload(BaseModel):
    version: int
    edits: list[_TextEdit] = Field(max_length=200)


class _Turn(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(max_length=4_000)


class _ChatPayload(BaseModel):
    version: int
    block_ids: list[str] = Field(default_factory=list, max_length=200)
    selected_text: str = Field(default="", max_length=10_000)
    message: str = Field(min_length=1, max_length=4_000)
    history: list[_Turn] = Field(default_factory=list, max_length=20)


def _initial_builder(db: Session, project: TranslationProject, user: User):
    def build() -> bytes:
        from app.routers.project import _resolve_rebuild_docx_bytes

        segments = (
            db.query(TranslationSegment)
            .filter(TranslationSegment.project_id == project.id)
            .order_by(TranslationSegment.segment_index)
            .all()
        )
        if not segments and not project.authored_docx_s3_key:
            raise HTTPException(status_code=404, detail="The translation isn't ready yet")
        project._export_user_email = user.email or ""
        project._export_user_logo_key = getattr(user, "logo_s3_key", None)
        return _resolve_rebuild_docx_bytes(project, segments, preview_only=True)

    return build


def _locked_project(db: Session, project_id: UUID, user: User) -> TranslationProject:
    get_user_project_or_404(db, project_id, user)
    return (
        db.query(TranslationProject)
        .filter(TranslationProject.id == project_id)
        .with_for_update()
        .populate_existing()
        .one()
    )


def _require_version(project: TranslationProject, version: int) -> None:
    if (project.document_version or 0) != version:
        raise HTTPException(status_code=409, detail="The document changed; reloaded the latest version")


@router.get("/{project_id}/document")
def get_document(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.routers.project import _can_download, _watermark_docx

    project = get_user_project_or_404(db, project_id, user)
    data, version = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    if not _can_download(db, user):
        data = _watermark_docx(data)
    return Response(
        content=data,
        media_type=DOCX_MEDIA,
        headers={"X-Document-Version": str(version), "Cache-Control": "no-store"},
    )


@router.post("/{project_id}/document/edits")
def edit_document(
    project_id: UUID,
    payload: _EditsPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _locked_project(db, project_id, user)
    _require_version(project, payload.version)
    data, _ = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    try:
        new_data, changed = docx_blocks.apply_text_edits(data, [(e.block_id, e.text) for e in payload.edits])
    except docx_blocks.DocxEditError:
        raise HTTPException(status_code=409, detail="The document changed; reloaded the latest version")
    if changed:
        document_editor.save_version(db, project, new_data, f"Edited {len(changed)} paragraph(s)", user)
        learning.record_changes(db, project, data, new_data, "typed")
    db.commit()
    return {"version": project.document_version}


@router.post(
    "/{project_id}/document/chat",
    dependencies=[Depends(user_rate_limit("doc_chat", max_requests=60, per_seconds=3600))],
)
def chat_document(
    project_id: UUID,
    payload: _ChatPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, user)
    _require_version(project, payload.version)
    data, _ = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    ai_allowance.reserve_edit(db, project, user)
    # The Claude call takes seconds to a minute, so the row is only locked to write the result.
    db.commit()
    try:
        with ai_usage.ai_context(action="document_chat", project_id=project.id, team_id=project.team_id, user_id=user.id):
            new_data, reply, changed = document_editor.chat_edit(
                project,
                data,
                payload.block_ids,
                payload.selected_text,
                payload.message,
                [t.model_dump() for t in payload.history],
            )
    except document_editor.ChatEditError as e:
        from app.services.ai_actions import is_staff

        detail = str(e)
        # Staff see the provider's reason so configuration problems can be diagnosed from the UI.
        if e.technical and is_staff(user):
            detail = f"{detail} [{e.technical}]"
        raise HTTPException(status_code=502, detail=detail)

    project = _locked_project(db, project_id, user)
    _require_version(project, payload.version)
    if changed or new_data is not data:
        document_editor.save_version(db, project, new_data, f"AI: {payload.message[:150]}", user)
        learning.record_changes(db, project, data, new_data, "chat")
    ai_allowance.count_edit(db, project, user)
    db.commit()
    return {
        "version": project.document_version,
        "reply": reply,
        "changed_block_ids": changed,
        "ai_edits_remaining": ai_allowance.remaining_included(project),
    }


@router.post("/{project_id}/document/undo")
def undo_document(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _locked_project(db, project_id, user)
    if not document_editor.undo(db, project):
        raise HTTPException(status_code=404, detail="Nothing to undo")
    db.commit()
    return {"version": project.document_version}
