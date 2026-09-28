"""Billing, locking and background execution for user-triggered AI work on an existing project."""
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.project import TranslationProject
from app.models.user import User
from app.services.credit_service import (
    CreditService,
    InsufficientCreditsError,
    WalletNotFoundError,
)
from app.services.project_lifecycle import revision_charge_reference

logger = logging.getLogger(__name__)

FREE_REVISIONS = int(os.getenv("FREE_REVISIONS_PER_PROJECT", "2"))
REBUILD_LOCK_MINUTES = 30
STAFF_ROLES = ("SUPERUSER", "SUPER_ADMIN", "ADMIN")


def is_staff(user: User) -> bool:
    return (user.role or "").upper() in STAFF_ROLES


def charge(db: Session, project: TranslationProject, user: User, reference: str) -> bool:
    """Deduct the project's page count. Returns False when nothing was charged (staff)."""
    if is_staff(user):
        return False
    try:
        CreditService.deduct_credits(
            db=db,
            team_id=str(project.team_id),
            amount=max(1, project.page_count or 1),
            reference_id=reference,
        )
    except InsufficientCreditsError:
        raise HTTPException(status_code=402, detail="Not enough credits for this action")
    except WalletNotFoundError:
        raise HTTPException(status_code=404, detail="Credit wallet not found")
    return True


def charge_revision(db: Session, project: TranslationProject, user: User) -> str | None:
    """Count a revision; charge page credits once the free allowance is used. Returns the charge reference."""
    project.revision_count = (project.revision_count or 0) + 1
    if project.revision_count <= FREE_REVISIONS:
        return None
    reference = revision_charge_reference(project.id, project.revision_count)
    return reference if charge(db, project, user, reference) else None


def claim_rebuild(project: TranslationProject) -> None:
    started = project.rebuild_started_at
    if (
        project.rebuild_status == "running"
        and started
        and started > datetime.utcnow() - timedelta(minutes=REBUILD_LOCK_MINUTES)
    ):
        raise HTTPException(status_code=409, detail="A rebuild is already running for this project")
    project.rebuild_status = "running"
    project.rebuild_error = None
    project.rebuild_started_at = datetime.utcnow()


def run_rebuild(project_id: str, instructions: str | None, charge_reference: str | None) -> None:
    """Background task: author a fresh DOCX from the source PDF; refund the charge on failure."""
    from app.database import SessionLocal
    from app.services.s3_service import download_file_from_s3, upload_file_to_s3

    db = SessionLocal()
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        project = db.query(TranslationProject).filter(TranslationProject.id == project_id).first()
        if not project:
            return
        try:
            src_path = tmp_dir / "source.pdf"
            download_file_from_s3(project.file_path, src_path)
            pdf_bytes = src_path.read_bytes()
            if instructions:
                from app.services.claude_multiturn_rebuild import author_rebuild_docx_multiturn

                docx_bytes = author_rebuild_docx_multiturn(
                    pdf_bytes,
                    project.source_language or "",
                    project.target_language or "",
                    extra_instructions=instructions,
                )
            else:
                from app.services.claude_authored_rebuild import author_rebuild_docx

                docx_bytes = author_rebuild_docx(
                    pdf_bytes=pdf_bytes,
                    source_lang=project.source_language or "",
                    target_lang=project.target_language or "",
                )
            out_path = tmp_dir / f"authored_{project.id}.docx"
            out_path.write_bytes(docx_bytes)
            project.authored_docx_s3_key = upload_file_to_s3(out_path)
            project.edited_html = None
            project.rebuild_status = "done"
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Rebuild failed for project %s", project_id)
            project.rebuild_status = "failed"
            project.rebuild_error = "The layout rebuild failed"
            if charge_reference:
                CreditService.refund_usage(db, charge_reference)
                project.rebuild_error += "; credits were refunded"
            db.commit()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        db.close()


def expire_stale_rebuilds(db: Session) -> int:
    """A rebuild still 'running' past the lock window lost its process (deploy/restart)."""
    cutoff = datetime.utcnow() - timedelta(minutes=REBUILD_LOCK_MINUTES)
    stale = (
        db.query(TranslationProject)
        .filter(
            TranslationProject.rebuild_status == "running",
            TranslationProject.rebuild_started_at < cutoff,
        )
        .all()
    )
    for project in stale:
        project.rebuild_status = "failed"
        project.rebuild_error = "The layout rebuild was interrupted; try again"
        if project.revision_count and project.revision_count > FREE_REVISIONS:
            CreditService.refund_usage(db, revision_charge_reference(project.id, project.revision_count))
    return len(stale)
