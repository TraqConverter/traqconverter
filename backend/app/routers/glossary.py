from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.glossary import Glossary

router = APIRouter(prefix="/glossary", tags=["Glossary"])


class GlossaryCreate(BaseModel):
    source_language: str
    target_language: str
    source_term: str
    target_term: str


# =========================================
# GET ALL TERMS
# =========================================
@router.get("")
def get_terms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    terms = db.query(Glossary).filter(
        Glossary.user_id == current_user.id
    ).all()

    return terms


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
    )

    db.add(term)
    db.commit()
    db.refresh(term)

    return term


# =========================================
# DELETE TERM
# =========================================
@router.delete("/{term_id}")
def delete_term(
    term_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    term = db.query(Glossary).filter(
        Glossary.id == term_id,
        Glossary.team_id == current_user.team_id
    ).first()

    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    db.delete(term)
    db.commit()

    return {"status": "deleted"}