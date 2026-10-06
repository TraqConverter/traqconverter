"""In-app notifications behind the header bell. Text carries file names, amounts and statuses, never a client's details."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.notification import KINDS, Notification

logger = logging.getLogger(__name__)

DEDUPE_WINDOW = timedelta(minutes=2)
READ_RETENTION = timedelta(days=90)


def notify(
    db: Session,
    user_id,
    kind: str,
    title: str,
    body: str = "",
    link: Optional[str] = None,
    project_id=None,
    team_id=None,
) -> Optional[Notification]:
    """Add a notification in the caller's transaction (the caller commits). Never raises."""
    if not user_id or kind not in KINDS:
        return None
    try:
        with db.begin_nested():
            recent = db.query(Notification.id).filter(
                Notification.user_id == user_id,
                Notification.kind == kind,
                Notification.created_at >= datetime.utcnow() - DEDUPE_WINDOW,
            )
            recent = recent.filter(
                Notification.project_id == project_id if project_id else Notification.project_id.is_(None)
            )
            if recent.first() is not None:
                return None
            row = Notification(
                user_id=user_id,
                team_id=team_id,
                kind=kind,
                title=(title or "")[:200],
                body=(body or "")[:500],
                link=link,
                project_id=project_id,
            )
            db.add(row)
        return row
    except Exception:
        logger.exception("Couldn't record a %s notification for user %s", kind, user_id)
        return None


def editor_link(project_id) -> str:
    return f"/editor/{project_id}"


def notify_project_people(db: Session, project, kind: str, title: str, body: str = "") -> None:
    """The uploader, and the assignee when that's someone else."""
    for user_id in _unique(project.user_id, getattr(project, "assignee_id", None)):
        notify(
            db, user_id, kind, title, body,
            link=editor_link(project.id), project_id=project.id, team_id=project.team_id,
        )


def translation_done(db: Session, project) -> None:
    target = project.target_language or ""
    notify_project_people(
        db, project, "translation_done",
        f"{project.file_name} is ready for review",
        f"Translated into {target}" if target else "",
    )


def translation_failed(db: Session, project) -> None:
    reason = (project.failure_reason or "").strip()
    notify_project_people(
        db, project, "translation_failed",
        f"{project.file_name} couldn't be translated",
        reason.splitlines()[0][:200] if reason else "",
    )


def _unique(*ids) -> list:
    seen, out = set(), []
    for i in ids:
        if i and str(i) not in seen:
            seen.add(str(i))
            out.append(i)
    return out


def purge_old_read(now: Optional[datetime] = None) -> int:
    """Delete read notifications older than READ_RETENTION; unread ones stay."""
    from app.database import SessionLocal

    cutoff = (now or datetime.utcnow()) - READ_RETENTION
    db = SessionLocal()
    try:
        deleted = (
            db.query(Notification)
            .filter(Notification.read_at.isnot(None), Notification.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        logger.exception("Couldn't purge old notifications")
        return 0
    finally:
        db.close()
