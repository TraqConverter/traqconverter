from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.models.segment_comment import SegmentComment
from app.models.translation_segment import TranslationSegment
from app.models.user import User

router = APIRouter(prefix="/segments", tags=["Segment Comments"])


class CommentCreate(BaseModel):
    text: str


# =========================================
# GET COMMENTS (WITH USER DATA + RESOLVED)
# =========================================
@router.get("/{segment_id}/comments")
def get_comments(
    segment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    results = db.query(SegmentComment, User).outerjoin(
        User, SegmentComment.user_id == User.id
    ).filter(
        SegmentComment.segment_id == segment_id
    ).order_by(
        SegmentComment.created_at.asc()
    ).all()

    return [
        {
            "id": c.id,
            "text": c.text,
            "created_at": c.created_at,
            "resolved": c.resolved,  # 🔥 IMPORTANT FIX
            "user": {
                "id": u.id if u else None,
                "email": u.email if u else "Unknown",
            }
        }
        for c, u in results
    ]


# =========================================
# CREATE COMMENT
# =========================================
@router.post("/{segment_id}/comments")
def create_comment(
    segment_id: UUID,
    data: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    segment = db.query(TranslationSegment).filter(
        TranslationSegment.id == segment_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    comment = SegmentComment(
        segment_id=segment_id,
        user_id=current_user.id,
        text=data.text
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {
        "id": comment.id,
        "text": comment.text,
        "created_at": comment.created_at,
        "resolved": comment.resolved,  # 🔥 IMPORTANT
        "user": {
            "id": current_user.id,
            "email": current_user.email,
        }
    }


# =========================================
# RESOLVE COMMENT
# =========================================
@router.patch("/{comment_id}/resolve")
def resolve_comment(
    comment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    comment = db.query(SegmentComment).filter(
        SegmentComment.id == comment_id
    ).first()

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    comment.resolved = True
    db.commit()

    return {"status": "resolved"}