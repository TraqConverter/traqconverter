from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.tenant import (
    get_user_project_or_404,
    assert_project_access,
)
from app.models.translation_segment import TranslationSegment
from app.models.project import TranslationProject
from app.models.user import User

from app.services.translation_memory_service import store_tm_entry

router = APIRouter(prefix="/segments", tags=["Segments"])


class SegmentUpdate(BaseModel):
    translated_text: str


# =========================================
# GET SEGMENTS FOR PROJECT — team scoped
# =========================================

@router.get("/project/{project_id}")
def get_segments(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project.id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    return [
        {
            "id": str(s.id),
            "segment_index": s.segment_index,
            "source_text": s.source_text,
            "translated_text": s.translated_text or "",
            "approved": bool(getattr(s, "approved", False)),
            "tm_pct": getattr(s, "tm_pct", None),
        }
        for s in segments
    ]


# =========================================
# UPDATE SEGMENT — team scoped (CRIT-1 fix)
# =========================================

@router.patch("/{segment_id}")
def update_segment(
    segment_id: UUID,
    data: SegmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    segment = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.id == segment_id)
        .first()
    )
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == segment.project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Tenant guard — reject segments that don't belong to a team this user is on.
    assert_project_access(db, project, current_user)

    segment.translated_text = data.translated_text
    db.commit()
    db.refresh(segment)

    # Store in Translation Memory (team scoped — same as before, but now
    # the underlying segment is verified to belong to the caller's team).
    try:
        store_tm_entry(
            db=db,
            team_id=project.team_id,
            source_language=project.source_language,
            target_language=project.target_language,
            source_text=segment.source_text,
            translated_text=data.translated_text,
        )
    except Exception:
        # TM write failures shouldn't fail the user's edit.
        pass

    return {
        "id": str(segment.id),
        "source_text": segment.source_text,
        "translated_text": segment.translated_text,
    }
