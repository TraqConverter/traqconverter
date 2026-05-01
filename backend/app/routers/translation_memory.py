from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.models.user import User
from app.models.team import Team
from app.models.translation_memory import TranslationMemory


# Both endpoints are Pro-only. Returning 403 lets the frontend render its
# upgrade-to-Pro paywall instead of guessing at empty data.
router = APIRouter(
    prefix="/tm",
    tags=["Translation Memory"],
    dependencies=[Depends(require_feature("terminology_memory"))],
)


# ============================================================
# LIST TM ENTRIES (with optional language filter + search)
# ============================================================

@router.get("/")
def list_tm_entries(
    source: str | None = Query(default=None, description="Source language filter"),
    target: str | None = Query(default=None, description="Target language filter"),
    q: str | None = Query(default=None, description="Substring search across source/target text"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = (
        db.query(Team).filter(Team.owner_id == current_user.id).first()
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    query = db.query(TranslationMemory).filter(TranslationMemory.team_id == team.id)

    if source:
        query = query.filter(TranslationMemory.source_language == source)
    if target:
        query = query.filter(TranslationMemory.target_language == target)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (TranslationMemory.source_text.ilike(like))
            | (TranslationMemory.translated_text.ilike(like))
        )

    rows = query.limit(limit).all()

    return [
        {
            "id": str(r.id),
            "source_language": r.source_language,
            "target_language": r.target_language,
            "source_text": r.source_text,
            "translated_text": r.translated_text,
        }
        for r in rows
    ]


# ============================================================
# TM SUMMARY (counts, language pairs, words saved estimate)
# ============================================================

@router.get("/summary")
def tm_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = (
        db.query(Team).filter(Team.owner_id == current_user.id).first()
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    total_units = (
        db.query(func.count(TranslationMemory.id))
        .filter(TranslationMemory.team_id == team.id)
        .scalar()
    ) or 0

    # Distinct language pairs
    pair_rows = (
        db.query(
            TranslationMemory.source_language,
            TranslationMemory.target_language,
            func.count(TranslationMemory.id).label("units"),
        )
        .filter(TranslationMemory.team_id == team.id)
        .group_by(
            TranslationMemory.source_language,
            TranslationMemory.target_language,
        )
        .all()
    )

    pairs = [
        {
            "source": r.source_language,
            "target": r.target_language,
            "units": int(r.units),
        }
        for r in pair_rows
    ]

    # Crude "words" estimate — sum of whitespace-split tokens in source text.
    # Done in Python because Postgres array_length on regexp_split is dialect-specific.
    word_estimate = 0
    for st in (
        db.query(TranslationMemory.source_text)
        .filter(TranslationMemory.team_id == team.id)
        .all()
    ):
        text = st[0] or ""
        word_estimate += len(text.split())

    return {
        "total_units": int(total_units),
        "language_pairs": pairs,
        "source_words_indexed": word_estimate,
    }
