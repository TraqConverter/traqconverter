"""The team's library of reusable instructions for the AI."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.models.saved_instruction import NAME_MAX, SavedInstruction
from app.models.user import User
from app.services import project_instructions

# Same plans as templates: Basic and Pro, not Trial.
router = APIRouter(
    prefix="/instructions",
    tags=["Saved instructions"],
    dependencies=[Depends(require_feature("templates"))],
)


class _Create(BaseModel):
    name: str
    text: str


class _Update(BaseModel):
    name: Optional[str] = None
    text: Optional[str] = None


def _team_id(db: Session, user: User):
    from app.dependencies.tenant import active_team_id

    team_id = active_team_id(db, user)
    if not team_id:
        raise HTTPException(status_code=400, detail="Team not found")
    return team_id


def _serialize(row: SavedInstruction) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "text": row.text,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise HTTPException(status_code=422, detail="Give the instructions a name")
    if len(name) > NAME_MAX:
        raise HTTPException(status_code=422, detail=f"The name can be at most {NAME_MAX} characters")
    return name


def _clean_text(text: str) -> str:
    try:
        cleaned = project_instructions.clean(text)
    except project_instructions.InstructionsTooLong as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not cleaned:
        raise HTTPException(status_code=422, detail="The instructions can't be empty")
    return cleaned


def _check_unique(db: Session, team_id, name: str, exclude=None) -> None:
    q = db.query(SavedInstruction.id).filter(
        SavedInstruction.team_id == team_id, func.lower(SavedInstruction.name) == name.lower()
    )
    if exclude is not None:
        q = q.filter(SavedInstruction.id != exclude)
    if q.first():
        raise HTTPException(status_code=409, detail=f"There's already saved instructions called “{name}”")


def _commit(db: Session, name: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"There's already saved instructions called “{name}”")


def _row(db: Session, team_id, instruction_id: UUID) -> SavedInstruction:
    row = (
        db.query(SavedInstruction)
        .filter(SavedInstruction.id == instruction_id, SavedInstruction.team_id == team_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Saved instructions not found")
    return row


@router.get("")
def list_instructions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(SavedInstruction)
        .filter(SavedInstruction.team_id == _team_id(db, user))
        .order_by(func.lower(SavedInstruction.name))
        .all()
    )
    return {"items": [_serialize(r) for r in rows]}


@router.post("", status_code=201)
def create_instruction(payload: _Create, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    team_id = _team_id(db, user)
    name, text = _clean_name(payload.name), _clean_text(payload.text)
    _check_unique(db, team_id, name)
    now = datetime.utcnow()
    row = SavedInstruction(team_id=team_id, name=name, text=text, created_by=user.id, created_at=now, updated_at=now)
    db.add(row)
    _commit(db, name)
    db.refresh(row)
    return _serialize(row)


@router.patch("/{instruction_id}")
def update_instruction(
    instruction_id: UUID, payload: _Update, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    team_id = _team_id(db, user)
    row = _row(db, team_id, instruction_id)
    if payload.name is not None:
        name = _clean_name(payload.name)
        _check_unique(db, team_id, name, exclude=row.id)
        row.name = name
    if payload.text is not None:
        row.text = _clean_text(payload.text)
    row.updated_at = datetime.utcnow()
    _commit(db, row.name)
    db.refresh(row)
    return _serialize(row)


@router.delete("/{instruction_id}")
def delete_instruction(instruction_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = _row(db, _team_id(db, user), instruction_id)
    db.delete(row)
    db.commit()
    return {"ok": True}
