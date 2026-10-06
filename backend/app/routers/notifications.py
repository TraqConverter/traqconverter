"""The current user's in-app notifications."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _serialize(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "kind": n.kind,
        "title": n.title,
        "body": n.body or "",
        "link": n.link,
        "project_id": str(n.project_id) if n.project_id else None,
        "created_at": n.created_at.isoformat() + "Z",
        "read_at": n.read_at.isoformat() + "Z" if n.read_at else None,
    }


@router.get("")
def list_notifications(
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mine = db.query(Notification).filter(Notification.user_id == current_user.id)
    items = mine.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    unread = mine.filter(Notification.read_at.is_(None)).count()
    return {"items": [_serialize(n) for n in items], "unread_count": unread}


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .update({Notification.read_at: datetime.utcnow()}, synchronize_session=False)
    )
    db.commit()
    return {"updated": updated, "unread_count": 0}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if n is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.read_at is None:
        n.read_at = datetime.utcnow()
        db.commit()
    return _serialize(n)
