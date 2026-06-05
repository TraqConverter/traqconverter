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


# =========================================
# EDIT COMMENT — author can change text anytime, even after it's
# been marked resolved. Path is /segments/comments/{id} so it
# doesn't collide with the segment update at /segments/{id}.
# =========================================

class CommentEdit(BaseModel):
    text: str


@router.patch("/comments/{comment_id}")
def edit_comment(
    comment_id: UUID,
    data: CommentEdit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    comment = (
        db.query(SegmentComment)
        .filter(SegmentComment.id == comment_id)
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    # Only the author can edit their own comment.
    if str(comment.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Only the author can edit this comment"
        )
    text = (data.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Comment can't be empty")
    comment.text = text
    db.commit()
    db.refresh(comment)
    return {
        "id": str(comment.id),
        "text": comment.text,
        "resolved": comment.resolved,
        "created_at": comment.created_at,
    }


# =========================================
# DELETE COMMENT — author OR project member; deletes work even on
# resolved comments. Lets reviewers clean up the discussion log.
# =========================================

@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    comment = (
        db.query(SegmentComment)
        .filter(SegmentComment.id == comment_id)
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    # Only the author can delete their own comment for now. (Owners
    # can take this further later if it becomes a need.)
    if str(comment.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403,
            detail="Only the author can delete this comment",
        )
    db.delete(comment)
    db.commit()
    return {"status": "deleted"}


# =========================================
# REOPEN COMMENT — flip resolved back to false. Lets reviewers
# revisit a discussion they prematurely marked resolved.
# =========================================

@router.patch("/comments/{comment_id}/reopen")
def reopen_comment(
    comment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    comment = (
        db.query(SegmentComment)
        .filter(SegmentComment.id == comment_id)
        .first()
    )
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    comment.resolved = False
    db.commit()
    db.refresh(comment)
    return {"status": "reopened", "resolved": False}