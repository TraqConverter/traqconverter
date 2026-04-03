from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.models.translation_segment import TranslationSegment
from app.models.project import TranslationProject
from app.models.user import User

from app.services.translation_memory_service import store_tm_entry

router = APIRouter(
    prefix="/segments",
    tags=["Segments"]
)

# =========================================
# Request schema for segment update
# =========================================

class SegmentUpdate(BaseModel):
    translated_text: str


# =========================================
# GET SEGMENTS FOR PROJECT
# =========================================

@router.get("/project/{project_id}")
def get_segments(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    project = db.query(TranslationProject).filter(
        TranslationProject.id == project_id
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    segments = db.query(TranslationSegment).filter(
        TranslationSegment.project_id == project_id
    ).order_by(
        TranslationSegment.segment_index
    ).all()

    return [
        {
            "id": s.id,
            "segment_index": s.segment_index,
            "source_text": s.source_text,
            "translated_text": s.translated_text
        }
        for s in segments
    ]


# =========================================
# UPDATE SEGMENT
# =========================================

@router.patch("/{segment_id}")
def update_segment(
    segment_id: UUID,
    data: SegmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    segment = db.query(TranslationSegment).filter(
        TranslationSegment.id == segment_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Update translation
    segment.translated_text = data.translated_text
    db.commit()

    # -------------------------------------
    # Store translation in Translation Memory
    # -------------------------------------
    project = db.query(TranslationProject).filter(
        TranslationProject.id == segment.project_id
    ).first()

    if project:
        store_translation(
            db=db,
            team_id=project.team_id,
            source_language=project.source_language,
            target_language=project.target_language,
            source_text=segment.source_text,
            translated_text=data.translated_text
        )

    return {
        "message": "Segment updated",
        "segment_id": segment_id
    }