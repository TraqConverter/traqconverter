from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.models.user import User
from app.models.glossary import Glossary

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
    }


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


# =========================================
# GET ALL TERMS
# =========================================
@router.get("")
def get_terms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    terms = (
        db.query(Glossary)
        .filter(Glossary.user_id == current_user.id)
        .order_by(Glossary.usage_count.desc())
        .all()
    )

    return [_serialize(t) for t in terms]


# =========================================
# CREATE TERM
# =========================================
@router.post("")
def create_term(
    data: GlossaryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    term = Glossary(
        user_id=current_user.id,
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


# =========================================
# UPDATE TERM (notes / wording)
# =========================================
@router.patch("/{term_id}")
def update_term(
    term_id: str,
    data: GlossaryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    term = (
        db.query(Glossary)
        .filter(Glossary.id == term_id, Glossary.user_id == current_user.id)
        .first()
    )

    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(term, field, value)

    db.commit()
    db.refresh(term)

    return _serialize(term)


# =========================================
# DELETE TERM
# =========================================
@router.delete("/{term_id}")
def delete_term(
    term_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    term = (
        db.query(Glossary)
        .filter(Glossary.id == term_id, Glossary.user_id == current_user.id)
        .first()
    )

    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    db.delete(term)
    db.commit()

    return {"status": "deleted"}
