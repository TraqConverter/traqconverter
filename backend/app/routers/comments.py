from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from pydantic import BaseModel

from app.database import get_db
from app.models.segment_comment import SegmentComment
from app.models.translation_segment import TranslationSegment
from app.models.user import User


router = APIRouter(
    prefix="/comments",
    tags=["comments"]
)


class CommentCreate(BaseModel):
    comment: str
    user_id: UUID


# --------------------------------
# Add comment to segment
# --------------------------------
@router.post("/{segment_id}")
def add_comment(
    segment_id: UUID,
    data: CommentCreate,
    db: Session = Depends(get_db)
):

    # Verify segment exists
    segment = db.query(TranslationSegment).filter(
        TranslationSegment.id == segment_id
    ).first()

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Verify user exists
    user = db.query(User).filter(
        User.id == data.user_id
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_comment = SegmentComment(
        segment_id=segment_id,
        user_id=data.user_id,
        comment=data.comment
    )

    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return {
        "id": new_comment.id,
        "segment_id": new_comment.segment_id,
        "user_id": new_comment.user_id,
        "comment": new_comment.comment,
        "created_at": new_comment.created_at
    }


# --------------------------------
# Get comments for a segment
# --------------------------------
@router.get("/{segment_id}")
def get_comments(segment_id: UUID, db: Session = Depends(get_db)):

    comments = db.query(SegmentComment).filter(
        SegmentComment.segment_id == segment_id
    ).order_by(SegmentComment.created_at).all()

    return comments