"""Shared state transitions for translation projects: queueing, failure and refunds."""
import logging
from datetime import datetime

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.models.credit import CreditTransaction
from app.models.project import ProjectStatus, TranslationProject
from app.services.credit_service import CreditService

logger = logging.getLogger(__name__)


def enqueue_job(db: Session, project_id: str, s3_key: str) -> None:
    """Insert a queue row in the caller's transaction so a charge never commits without its job."""
    db.execute(
        text(
            "INSERT INTO translation_jobs (project_id, s3_key, status) "
            "VALUES (:project_id, :s3_key, 'pending')"
        ),
        {"project_id": str(project_id), "s3_key": s3_key},
    )


def job_charge_reference(project_id, attempt: int | None = None) -> str:
    return str(project_id) if not attempt else f"{project_id}:rerun:{attempt}"


def latest_job_charge(db: Session, project_id) -> str | None:
    pid = str(project_id)
    row = (
        db.query(CreditTransaction.reference_id)
        .filter(
            CreditTransaction.type == "USAGE",
            or_(
                CreditTransaction.reference_id == pid,
                CreditTransaction.reference_id.like(f"{pid}:rerun:%"),
            ),
        )
        .order_by(CreditTransaction.created_at.desc())
        .first()
    )
    return row[0] if row else None


def mark_project_failed(db: Session, project: TranslationProject, reason: str) -> int:
    """Mark FAILED and refund the charge for the run that failed. Caller commits."""
    project.status = ProjectStatus.FAILED
    project.failure_reason = (reason or "Processing failed")[:500]
    project.last_heartbeat = datetime.utcnow()
    refunded = 0
    reference = latest_job_charge(db, project.id)
    if reference:
        refunded = CreditService.refund_usage(db, reference)
    if refunded:
        logger.info("Refunded %d credits for failed project %s", refunded, project.id)
    return refunded


def fail_project_by_id(project_id: str, reason: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        project = db.query(TranslationProject).filter(TranslationProject.id == project_id).first()
        if project and project.status != ProjectStatus.COMPLETED:
            mark_project_failed(db, project, reason)
            db.commit()
            _broadcast(project)
    except Exception:
        db.rollback()
        logger.exception("Couldn't mark project %s failed", project_id)
    finally:
        db.close()


def _broadcast(project: TranslationProject) -> None:
    try:
        from app.services.translation_processor import safe_broadcast

        safe_broadcast(str(project.id), project.progress_percent or 0, project.status.value)
    except Exception:
        logger.debug("broadcast skipped", exc_info=True)
