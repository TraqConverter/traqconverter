"""Templates and learned terminology: what the tool has learned for a team, and what it used on a project."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.plan_features import PLAN_FEATURES
from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import effective_plan, require_feature
from app.dependencies.rate_limit import user_rate_limit
from app.dependencies.tenant import get_user_project_or_404, team_ids_for
from app.models.glossary import Glossary
from app.models.learning import DocumentTemplate
from app.models.project import ProjectStatus
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.user import User
from app.services import learning, template_upload, tm_keys
from app.services.glossary_service import lang_key, language_name

router = APIRouter(tags=["Learning"])


def _template(t: DocumentTemplate) -> dict:
    profile = t.doc_profile or {}
    return {
        "id": str(t.id),
        "title": t.title,
        "doc_key": t.doc_key,
        "document_type": profile.get("document_type") or "",
        "issuing_authority": profile.get("issuing_authority") or "",
        "country": profile.get("country") or "",
        "target_language": t.target_language,
        "target_language_name": language_name(t.target_language),
        "source_project_id": str(t.source_project_id) if t.source_project_id else None,
        "use_count": t.use_count or 0,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _term(g: Glossary) -> dict:
    return {
        "id": str(g.id),
        "source_term": g.source_term,
        "target_term": g.target_term,
        "source_language": g.source_language,
        "target_language": g.target_language,
        "origin": g.origin,
        "confidence": g.confidence,
        "usage_count": g.usage_count or 0,
        "learned_from_project_id": str(g.learned_from_project_id) if g.learned_from_project_id else None,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


@router.get("/templates")
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    teams = team_ids_for(db, user)
    if not teams:
        return []
    rows = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.team_id.in_(teams))
        .order_by(DocumentTemplate.updated_at.desc())
        .all()
    )
    return [_template(t) for t in rows]


@router.delete("/templates/{template_id}")
def delete_template(template_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.s3_service import delete_objects_from_s3

    template = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.id == template_id, DocumentTemplate.team_id.in_(team_ids_for(db, user)))
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    key = template.s3_key
    db.delete(template)
    db.commit()
    try:
        delete_objects_from_s3([key])
    except Exception:
        pass
    return {"status": "deleted"}


@router.post("/projects/{project_id}/template")
def save_as_template(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_user_project_or_404(db, project_id, user)
    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="The translation isn't finished yet")
    if not learning.ensure_profile(db, project):
        raise HTTPException(status_code=422, detail="Couldn't identify the document type")
    template = learning.capture_template(db, project, user)
    if not template:
        raise HTTPException(status_code=422, detail="Couldn't save this document as a template")
    return _template(template)


class _FromUpload(BaseModel):
    upload_id: UUID
    target_language: str = Field(min_length=1, max_length=40)
    document_type: str = Field(min_length=1, max_length=120)
    country: str = Field(default="", max_length=120)
    issuing_authority: str = Field(default="", max_length=120)
    format_variant: str = Field(default="", max_length=120)
    source_language: str = Field(default="", max_length=60)


def _upload_team_id(db: Session, user: User):
    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if team:
        return team.id
    membership = db.query(TeamMember).filter(TeamMember.user_id == user.id).first()
    if membership:
        return membership.team_id
    raise HTTPException(status_code=404, detail="No team found")


def _read_upload(file: UploadFile) -> bytes:
    # One byte over the limit is enough to reject it.
    return file.file.read(template_upload.MAX_BYTES + 1)


def _existing(t: Optional[DocumentTemplate]) -> Optional[dict]:
    if not t:
        return None
    return {"id": str(t.id), "title": t.title, "target_language_name": language_name(t.target_language)}


@router.post(
    "/templates/analyze",
    dependencies=[
        Depends(require_feature("template_upload")),
        Depends(user_rate_limit("template_upload", max_requests=30, per_seconds=3600)),
    ],
)
def analyze_upload(
    original: UploadFile = File(...),
    translation: UploadFile = File(...),
    target_language: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    team_id = _upload_team_id(db, user)
    try:
        row = template_upload.analyze(
            db, team_id, user.id,
            original.filename or "", _read_upload(original),
            translation.filename or "", _read_upload(translation),
            target_language.strip(),
        )
    except template_upload.UploadError as e:
        raise HTTPException(status_code=422, detail=str(e))
    profile = row.profile or {}
    return {
        "upload_id": str(row.id),
        "expires_at": row.expires_at.isoformat(),
        "target_language": row.target_language,
        "target_language_name": language_name(lang_key(row.target_language)),
        "profile": {k: profile.get(k) or "" for k in template_upload.PROFILE_FIELDS},
        "title": learning.profile_title(profile),
        "doc_key": profile.get("doc_key") or "",
        "source_lines": len(row.source_lines or []),
        "existing_template": _existing(
            template_upload.existing_template(db, team_id, profile.get("doc_key") or "", row.target_language)
        ),
    }


@router.get("/templates/key-check", dependencies=[Depends(require_feature("template_upload"))])
def check_template_key(
    upload_id: UUID,
    target_language: str = Query(..., max_length=40),
    document_type: str = Query("", max_length=120),
    country: str = Query("", max_length=120),
    issuing_authority: str = Query("", max_length=120),
    format_variant: str = Query("", max_length=120),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The key and title the edited profile gives, and the template it would replace."""
    row = template_upload.pending_for(db, upload_id, team_ids_for(db, user))
    if not row:
        raise HTTPException(status_code=404, detail="Upload not found")
    profile = template_upload.clean_profile({
        "document_type": document_type, "country": country,
        "issuing_authority": issuing_authority, "format_variant": format_variant,
    })
    return {
        "doc_key": profile["doc_key"],
        "title": learning.profile_title(profile),
        "existing_template": _existing(
            template_upload.existing_template(db, row.team_id, profile["doc_key"], target_language)
        ),
    }


@router.post("/templates/from-upload", dependencies=[Depends(require_feature("template_upload"))])
def template_from_upload(
    payload: _FromUpload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = template_upload.pending_for(db, payload.upload_id, team_ids_for(db, user), lock=True)
    if not row:
        raise HTTPException(status_code=404, detail="Upload not found")
    if template_upload.is_expired(row):
        keys = [row.original_key, row.translation_key]
        db.delete(row)
        db.commit()
        template_upload._delete_files(keys)
        raise HTTPException(status_code=410, detail="This upload expired. Upload the two files again.")
    team_id, lines = row.team_id, list(row.source_lines or [])
    fields = payload.model_dump(exclude={"upload_id", "target_language"})
    try:
        template, replaced, profile, data = template_upload.save_template(db, row, fields, payload.target_language.strip())
    except template_upload.UploadError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))

    added, note = 0, None
    if not PLAN_FEATURES.get(effective_plan(db, user), {}).get("terminology_memory"):
        note = "The translation memory is part of the Pro plan, so no lines were added."
    elif not tm_keys.source_lang(profile.get("source_language")):
        note = "The source language wasn't recognised, so no lines were added to the memory."
    else:
        added = template_upload.align_memory(
            db, team_id, user.id, lines, data, profile["source_language"], payload.target_language,
        )
    return {
        "template": _template(template),
        "replaced": replaced,
        "memory_lines_added": added,
        "memory_note": note,
    }


@router.get("/projects/{project_id}/learning")
def project_learning(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_user_project_or_404(db, project_id, user)
    used = None
    if project.template_id:
        t = db.query(DocumentTemplate).filter(DocumentTemplate.id == project.template_id).first()
        if t:
            used = {"id": str(t.id), "title": t.title, "created_at": t.created_at.isoformat() if t.created_at else None}
    saved = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.source_project_id == project.id, DocumentTemplate.team_id == project.team_id)
        .first()
    )
    learned = (
        db.query(Glossary)
        .filter(Glossary.learned_from_project_id == project.id, Glossary.origin == "learned")
        .order_by(Glossary.created_at.desc())
        .all()
    )
    applied = learning.team_terms(db, project, learning.source_text_of(db, project))
    return {
        "template_used": used,
        "saved_as_template": {"id": str(saved.id), "title": saved.title} if saved else None,
        "doc_profile": project.doc_profile,
        "terms_applied": [_term(g) for g in applied],
        "terms_learned_here": [_term(g) for g in learned],
    }


@router.get("/learning/summary")
def learning_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    teams = team_ids_for(db, user)
    if not teams:
        return {"templates": 0, "learned_terms": 0, "recent_terms": []}
    learned = db.query(Glossary).filter(Glossary.team_id.in_(teams), Glossary.origin == "learned")
    return {
        "templates": db.query(DocumentTemplate).filter(DocumentTemplate.team_id.in_(teams)).count(),
        "learned_terms": learned.count(),
        "recent_terms": [_term(g) for g in learned.order_by(Glossary.created_at.desc()).limit(10).all()],
    }


@router.post("/learning/terms/{term_id}/reject")
def reject_term(term_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    term = (
        db.query(Glossary)
        .filter(Glossary.id == term_id, Glossary.team_id.in_(team_ids_for(db, user)))
        .first()
    )
    if not term or term.origin not in ("learned", "rejected"):
        raise HTTPException(status_code=404, detail="Term not found")
    # Kept as 'rejected' so the same pair isn't learned again from later edits.
    term.origin = "rejected"
    db.commit()
    return {"status": "rejected"}
