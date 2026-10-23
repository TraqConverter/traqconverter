from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.dependencies.tenant import is_team_lead, require_team_lead, team_ids_for
from app.models.user import User
from app.models.glossary import Glossary
from app.services import glossary_transfer, safe_xml

router = APIRouter(
    prefix="/glossary",
    tags=["Glossary"],
    dependencies=[Depends(require_feature("glossaries"))],
)


def _serialize(term: Glossary) -> dict:
    return {
        "id": str(term.id),
        "source_language": term.source_language,
        "target_language": term.target_language,
        "source_term": term.source_term,
        "target_term": term.target_term,
        "notes": term.notes,
        "usage_count": term.usage_count or 0,
        "origin": term.origin or "manual",
        "confidence": term.confidence,
    }


def _user_team_id(db: Session, user: User):
    """Glossary is team-scoped. The owner's team is canonical; members
    fall back to the team they joined."""
    from app.dependencies.tenant import active_team_id

    return active_team_id(db, user)


class GlossaryCreate(BaseModel):
    source_language: str
    target_language: str
    source_term: str
    target_term: str
    notes: Optional[str] = None


class GlossaryUpdate(BaseModel):
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    source_term: Optional[str] = None
    target_term: Optional[str] = None
    notes: Optional[str] = None





@router.get("")
def get_terms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_teams = team_ids_for(db, current_user)
    if not allowed_teams:
        return []
    terms = (
        db.query(Glossary)
        .filter(Glossary.team_id.in_(allowed_teams), Glossary.origin != "rejected")
        .order_by(Glossary.usage_count.desc())
        .all()
    )
    return [_serialize(t) for t in terms]





@router.post("")
def create_term(
    data: GlossaryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team_id = _user_team_id(db, current_user)
    if not team_id:
        raise HTTPException(status_code=400, detail="No team found for this user")

    term = Glossary(
        team_id=team_id,
        source_language=data.source_language,
        target_language=data.target_language,
        source_term=data.source_term,
        target_term=data.target_term,
        notes=data.notes,
        usage_count=0,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return _serialize(term)





@router.patch("/{term_id}")
def update_term(
    term_id: UUID,
    data: GlossaryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_teams = team_ids_for(db, current_user)
    term = (
        db.query(Glossary)
        .filter(Glossary.id == term_id, Glossary.team_id.in_(allowed_teams))
        .first(
        )
    )
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(term, field, value)
    if payload:
        term.origin = "manual"

    db.commit()
    db.refresh(term)
    return _serialize(term)





@router.delete("/{term_id}")
def delete_term(
    term_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_teams = team_ids_for(db, current_user)
    term = (
        db.query(Glossary)
        .filter(Glossary.id == term_id, Glossary.team_id.in_(allowed_teams))
        .first()
    )
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    db.delete(term)
    db.commit()
    return {"status": "deleted"}


def _lead_team_id(db: Session, user: User, action: str):
    team_id = _user_team_id(db, user)
    if not team_id:
        raise HTTPException(status_code=400, detail="No team found for this user")
    require_team_lead(db, team_id, user, action)
    return team_id


@router.get("/access")
def glossary_access(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team_id = _user_team_id(db, current_user)
    return {"can_transfer": bool(team_id) and is_team_lead(db, team_id, current_user)}


@router.get("/export")
def export_glossary(
    format: str = Query(default="csv", pattern="^(csv|tbx)$"),
    source: Optional[str] = Query(default=None),
    target: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team_id = _lead_team_id(db, current_user, "export the glossary")
    terms = glossary_transfer.terms_for_export(db, team_id, source or "", target or "")
    if not terms:
        raise HTTPException(status_code=404, detail="There are no terms to export for this language pair")
    if format == "tbx":
        body, media = glossary_transfer.build_tbx(terms), "application/x-tbx+xml"
    else:
        body, media = glossary_transfer.build_csv(terms), "text/csv; charset=utf-8"
    name = "-".join(["glossary", *(glossary_transfer.export_code(x) for x in (source, target) if x)])
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}.{format}"', "Cache-Control": "no-store"},
    )


@router.post("/import")
def import_glossary(
    file: UploadFile = File(...),
    source: Optional[str] = Query(default=None, max_length=40, description="Source language; the file's first language when empty"),
    replace: bool = Query(default=False, description="Replace a different translation the team already has"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team_id = _lead_team_id(db, current_user, "import into the glossary")
    data = file.file.read(glossary_transfer.MAX_BYTES + 1)
    if len(data) > glossary_transfer.MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"The file is larger than {safe_xml.size_label(glossary_transfer.MAX_BYTES)}")
    try:
        fmt, pairs, invalid = glossary_transfer.read_upload(data, source or "")
    except (safe_xml.XmlError, glossary_transfer.GlossaryFileError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    counts = glossary_transfer.import_terms(db, team_id, pairs, replace=replace)
    counts["invalid"] += invalid
    skipped = counts["duplicates"] + counts["conflicts"] + counts["unsupported_language"] + counts["invalid"]
    return {"format": fmt, "rows": len(pairs) + invalid, **counts, "skipped": skipped}
