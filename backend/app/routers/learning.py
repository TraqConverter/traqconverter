"""Templates and learned terminology: what the tool has learned for a team, and what it used on a project."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.tenant import get_user_project_or_404, team_ids_for
from app.models.glossary import Glossary
from app.models.learning import DocumentTemplate
from app.models.project import ProjectStatus
from app.models.user import User
from app.services import learning
from app.services.glossary_service import language_name

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
