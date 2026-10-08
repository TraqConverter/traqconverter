"""Automatic deletion: a project goes DOCUMENT_RETENTION_DAYS after its translation last completed."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.project import ProjectStatus, TranslationProject

logger = logging.getLogger(__name__)

WARN_BEFORE = timedelta(days=7)
RUN_EVERY = timedelta(hours=1)
BATCH = 50
WARNING_KIND = "files_expiring"
# Any constant works; it only has to differ from other advisory locks taken on this database.
LOCK_KEY = 7_340_921_090
ACTIVE = (ProjectStatus.PENDING, ProjectStatus.PROCESSING)

_last_run: Optional[datetime] = None


def retention_days() -> int:
    from app.config import settings

    return max(0, int(settings.DOCUMENT_RETENTION_DAYS or 0))


def _anchor():
    return func.coalesce(TranslationProject.retention_from, TranslationProject.created_at)


def deletes_on(project: TranslationProject) -> Optional[datetime]:
    """When the project will be deleted; None while it is queued or running, or when deletion is off."""
    days = retention_days()
    if not days or project.status in ACTIVE:
        return None
    start = project.retention_from or project.created_at
    return start + timedelta(days=days) if start else None


def warn_upcoming(db: Session, now: Optional[datetime] = None) -> int:
    from app.services import notifications

    days = retention_days()
    if not days:
        return 0
    now = now or datetime.utcnow()
    due = now - timedelta(days=days)
    rows = (
        db.query(TranslationProject)
        .filter(
            TranslationProject.status.notin_(ACTIVE),
            _anchor() > due,
            _anchor() <= due + WARN_BEFORE,
        )
        .limit(200)
        .all()
    )
    sent = 0
    for project in rows:
        start = project.retention_from or project.created_at
        warned = (
            db.query(Notification.id)
            .filter(
                Notification.project_id == project.id,
                Notification.kind == WARNING_KIND,
                Notification.created_at >= start,
            )
            .first()
        )
        if warned:
            continue
        when = deletes_on(project)
        notifications.notify_project_people(
            db, project, WARNING_KIND,
            f"{project.file_name} will be deleted on {when:%-d %B %Y}",
            "Download anything you still need. Translation memory and glossary entries are kept.",
        )
        sent += 1
    db.commit()
    return sent


def purge_expired(db: Session, now: Optional[datetime] = None) -> int:
    from app.services import project_files

    days = retention_days()
    if not days:
        return 0
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    ids = [
        pid for (pid,) in db.query(TranslationProject.id)
        .filter(TranslationProject.status.notin_(ACTIVE), _anchor() <= cutoff)
        .limit(BATCH)
    ]
    deleted = 0
    for pid in ids:
        # Locked and checked again: a rerun started since the query moves the project out of reach.
        project = (
            db.query(TranslationProject)
            .filter(TranslationProject.id == pid, TranslationProject.status.notin_(ACTIVE), _anchor() <= cutoff)
            .with_for_update(skip_locked=True)
            .first()
        )
        if project is None:
            db.rollback()
            continue
        try:
            project_files.delete_project(db, project, keep_memory=True)
            deleted += 1
        except Exception:
            logger.exception("Couldn't delete expired project %s", pid)
    if deleted:
        logger.info("Deleted %d projects past the %d-day retention period", deleted, days)
    return deleted


def run(now: Optional[datetime] = None) -> int:
    """One pass, on whichever instance takes the advisory lock first; the others skip."""
    from app.database import SessionLocal, engine

    with engine.connect() as conn:
        if not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
            return 0
        try:
            db = SessionLocal()
            try:
                warn_upcoming(db, now)
                return purge_expired(db, now)
            except Exception:
                db.rollback()
                logger.exception("Document retention pass failed")
                return 0
            finally:
                db.close()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            conn.commit()


def run_if_due(now: Optional[datetime] = None) -> int:
    from app.services import source_pages

    global _last_run
    now = now or datetime.utcnow()
    if _last_run and now - _last_run < RUN_EVERY:
        return 0
    _last_run = now
    source_pages.purge_stale()
    return run(now)
