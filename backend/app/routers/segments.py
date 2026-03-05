from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.dependencies import get_current_user
from app.models.translation_segment import TranslationSegment
from app.models.project import TranslationProject
from app.models.user import User

router = APIRouter(
    prefix="/segments",
    tags=["Segments"]
)


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
    translated_text: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    segment = db.query(TranslationSegment).filter(
        TranslationSegment.id == segment_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    segment.translated_text = translated_text

    db.commit()

    return {"message": "Segment updated"}