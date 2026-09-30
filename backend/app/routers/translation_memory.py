import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.models.project import TranslationProject
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.translation_memory import TranslationMemory
from app.models.user import User
from app.services import tm_keys, tmx
from app.services.translation_memory_service import upsert_entries


def _resolve_user_team(db: Session, user: User) -> Team:
    """Owner-or-member team lookup; TM is team-scoped."""
    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if team:
        return team
    membership = (
        db.query(TeamMember).filter(TeamMember.user_id == user.id).first()
    )
    if membership:
        team = (
            db.query(Team).filter(Team.id == membership.team_id).first()
        )
        if team:
            return team
    raise HTTPException(status_code=404, detail="Team not found")


router = APIRouter(
    prefix="/tm",
    tags=["Translation Memory"],
    dependencies=[Depends(require_feature("terminology_memory"))],
)

IMPORT_CHUNK = 1000


def _serialize(r: TranslationMemory, project_name: Optional[str] = None) -> dict:
    return {
        "id": str(r.id),
        "source_language": r.source_language,
        "target_language": r.target_language,
        "source_text": r.source_text,
        "translated_text": r.translated_text,
        "origin": r.origin,
        "project_id": str(r.project_id) if r.project_id else None,
        "project_name": project_name,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _entry_or_404(db: Session, team: Team, entry_id: UUID) -> TranslationMemory:
    row = (
        db.query(TranslationMemory)
        .filter(TranslationMemory.id == entry_id, TranslationMemory.team_id == team.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    return row


def _filtered(db: Session, team: Team, source=None, target=None, origin=None, project_id=None, q=None):
    query = db.query(TranslationMemory).filter(TranslationMemory.team_id == team.id)
    if source:
        query = query.filter(TranslationMemory.source_language == (tm_keys.source_lang(source) or source))
    if target:
        query = query.filter(TranslationMemory.target_language == (tm_keys.target_lang(target) or target))
    if origin:
        query = query.filter(TranslationMemory.origin == origin)
    if project_id:
        query = query.filter(TranslationMemory.project_id == project_id)
    if q and q.strip():
        like = "%" + re.sub(r"([%_\\])", r"\\\1", q.strip()) + "%"
        query = query.filter(
            TranslationMemory.source_text.ilike(like, escape="\\")
            | TranslationMemory.translated_text.ilike(like, escape="\\")
        )
    return query


@router.get("/")
def list_tm_entries(
    source: Optional[str] = Query(default=None, description="Source language filter"),
    target: Optional[str] = Query(default=None, description="Target language filter"),
    origin: Optional[str] = Query(default=None, pattern="^(machine|approved|manual|import)$"),
    project_id: Optional[UUID] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=500, description="Substring search across source/target text"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_user_team(db, current_user)
    query = _filtered(db, team, source, target, origin, project_id, q)
    total = query.count()
    rows = (
        query.outerjoin(TranslationProject, TranslationProject.id == TranslationMemory.project_id)
        .add_columns(TranslationProject.file_name)
        .order_by(TranslationMemory.updated_at.desc(), TranslationMemory.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [_serialize(r, name) for r, name in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/summary")
def tm_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_user_team(db, current_user)
    base = db.query(TranslationMemory).filter(TranslationMemory.team_id == team.id)
    pair_rows = (
        base.with_entities(
            TranslationMemory.source_language,
            TranslationMemory.target_language,
            func.count(TranslationMemory.id),
        )
        .group_by(TranslationMemory.source_language, TranslationMemory.target_language)
        .all()
    )
    origin_rows = (
        base.with_entities(TranslationMemory.origin, func.count(TranslationMemory.id))
        .group_by(TranslationMemory.origin)
        .all()
    )
    words = base.with_entities(
        func.coalesce(func.sum(func.array_length(func.regexp_split_to_array(func.trim(TranslationMemory.source_text), r"\s+"), 1)), 0)
    ).scalar()
    project_rows = (
        base.join(TranslationProject, TranslationProject.id == TranslationMemory.project_id)
        .with_entities(TranslationProject.id, TranslationProject.file_name, func.count(TranslationMemory.id))
        .group_by(TranslationProject.id, TranslationProject.file_name)
        .order_by(func.max(TranslationMemory.updated_at).desc())
        .limit(100)
        .all()
    )
    pairs = sorted(
        ({"source": s, "target": t, "units": int(n)} for s, t, n in pair_rows),
        key=lambda p: -p["units"],
    )
    origins = {o: 0 for o in tm_keys.ORIGINS}
    origins.update({o: int(n) for o, n in origin_rows})
    return {
        "total_units": sum(p["units"] for p in pairs),
        "language_pairs": pairs,
        "origins": origins,
        "projects": [{"id": str(i), "name": name, "units": int(n)} for i, name, n in project_rows],
        "source_words_indexed": int(words or 0),
    }


class _EntryCreate(BaseModel):
    source_language: str = Field(min_length=2, max_length=40)
    target_language: str = Field(min_length=2, max_length=40)
    source_text: str = Field(min_length=1, max_length=tm_keys.MAX_SOURCE_CHARS)
    translated_text: str = Field(min_length=1, max_length=10_000)


class _EntryUpdate(BaseModel):
    source_text: Optional[str] = Field(default=None, min_length=1, max_length=tm_keys.MAX_SOURCE_CHARS)
    translated_text: Optional[str] = Field(default=None, min_length=1, max_length=10_000)


class _BulkDelete(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=1000)


def _pair_or_400(source_language: str, target_language: str) -> tuple[str, str]:
    src, tgt = tm_keys.source_lang(source_language), tm_keys.target_lang(target_language)
    if not src or not tgt:
        raise HTTPException(status_code=400, detail="Pick a source and a target language")
    return src, tgt


def _clean(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text can't be empty")
    return text


@router.post("/")
def create_tm_entry(
    data: _EntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_user_team(db, current_user)
    src, tgt = _pair_or_400(data.source_language, data.target_language)
    source, target = _clean(data.source_text), _clean(data.translated_text)
    written = upsert_entries(db, team.id, [{
        "source_language": src, "target_language": tgt, "source_text": source,
        "translated_text": target, "origin": "manual",
    }])
    if not written:
        raise HTTPException(status_code=500, detail="Couldn't save the entry")
    row = (
        db.query(TranslationMemory)
        .filter(
            TranslationMemory.team_id == team.id,
            TranslationMemory.source_language == src,
            TranslationMemory.target_language == tgt,
            TranslationMemory.source_hash == tm_keys.source_hash(source),
        )
        .one()
    )
    return _serialize(row)


@router.patch("/{entry_id}")
def update_tm_entry(
    entry_id: UUID,
    data: _EntryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_user_team(db, current_user)
    row = _entry_or_404(db, team, entry_id)
    if data.source_text is not None:
        source = _clean(data.source_text)
        new_hash = tm_keys.source_hash(source)
        if new_hash != row.source_hash:
            clash = (
                db.query(TranslationMemory.id)
                .filter(
                    TranslationMemory.team_id == team.id,
                    TranslationMemory.source_language == row.source_language,
                    TranslationMemory.target_language == row.target_language,
                    TranslationMemory.source_hash == new_hash,
                    TranslationMemory.id != row.id,
                )
                .first()
            )
            if clash:
                raise HTTPException(status_code=409, detail="Another entry already has this source text")
        row.source_text, row.source_hash = source, new_hash
    if data.translated_text is not None:
        row.translated_text = _clean(data.translated_text)
    row.origin = "manual"
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{entry_id}")
def delete_tm_entry(
    entry_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_user_team(db, current_user)
    row = _entry_or_404(db, team, entry_id)
    db.delete(row)
    db.commit()
    return {"deleted": 1}


@router.post("/bulk-delete")
def bulk_delete_tm_entries(
    data: _BulkDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_user_team(db, current_user)
    deleted = (
        db.query(TranslationMemory)
        .filter(TranslationMemory.team_id == team.id, TranslationMemory.id.in_(data.ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": int(deleted)}


@router.post("/import")
async def import_tmx(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_user_team(db, current_user)
    data = await file.read(tmx.MAX_BYTES + 1)
    if len(data) > tmx.MAX_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 10 MB")
    try:
        pairs, units = tmx.parse(data)
    except tmx.TmxError as e:
        raise HTTPException(status_code=400, detail=str(e))
    usable = [
        dict(p, origin="import")
        for p in pairs
        if tm_keys.source_lang(p["source_language"]) and tm_keys.target_lang(p["target_language"])
        and p["source_text"].strip() and p["translated_text"].strip()
        and len(p["source_text"]) <= tm_keys.MAX_SOURCE_CHARS
    ]
    written = 0
    for i in range(0, len(usable), IMPORT_CHUNK):
        written += upsert_entries(db, team.id, usable[i:i + IMPORT_CHUNK])
    return {"units": units, "pairs": len(pairs), "imported": written, "skipped": len(pairs) - len(usable)}


@router.get("/export")
def export_tmx(
    source: Optional[str] = Query(default=None),
    target: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_user_team(db, current_user)
    rows = (
        _filtered(db, team, source, target)
        .order_by(TranslationMemory.source_language, TranslationMemory.target_language, TranslationMemory.created_at)
        .all()
    )
    src = tm_keys.source_lang(source) if source else ""
    body = tmx.build(rows, srclang=src or "*all*")
    name = "translation-memory"
    if source or target:
        name += "-" + "-".join(x for x in (src, tm_keys.target_lang(target) if target else "") if x)
    return Response(
        content=body,
        media_type="application/x-tmx+xml",
        headers={"Content-Disposition": f'attachment; filename="{name}.tmx"', "Cache-Control": "no-store"},
    )
