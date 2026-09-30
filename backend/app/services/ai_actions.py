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

logger = logging.getLogger(__name__)

REGENERATE_LIMIT = int(os.getenv("REGENERATE_LIMIT_PER_PROJECT", "2"))
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


def regenerations_left(project: TranslationProject) -> int:
    return max(0, REGENERATE_LIMIT - (project.revision_count or 0))


def use_regeneration(project: TranslationProject) -> None:
    """Count a regenerate or revise against the per-document limit; they are never charged."""
    if regenerations_left(project) <= 0:
        raise HTTPException(status_code=403, detail=f"Regenerate is limited to {REGENERATE_LIMIT} per document")
    project.revision_count = (project.revision_count or 0) + 1


def return_regeneration(project: TranslationProject) -> None:
    """A failed attempt doesn't count against the limit."""
    project.revision_count = max(0, (project.revision_count or 0) - 1)


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


def run_rebuild(project_id: str, instructions: str | None) -> None:
    """Background task: author a fresh DOCX from the source PDF using the saved and this regenerate's instructions; a failure gives the attempt back."""
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
            from app.services.learning import source_text_of, team_terminology
            from app.services.translation_memory_service import with_memory

            source_text = source_text_of(db, project)
            terminology = with_memory(db, project, team_terminology(db, project, source_text), source_text)
            saved = project.ai_instructions or ""
            if instructions:
                from app.services.claude_multiturn_rebuild import author_rebuild_docx_multiturn

                docx_bytes = author_rebuild_docx_multiturn(
                    pdf_bytes,
                    project.source_language or "",
                    project.target_language or "",
                    extra_instructions=instructions,
                    terminology=terminology,
                    instructions=saved,
                )
            else:
                from app.services.claude_authored_rebuild import author_rebuild_docx

                docx_bytes = author_rebuild_docx(
                    pdf_bytes=pdf_bytes,
                    source_lang=project.source_language or "",
                    target_lang=project.target_language or "",
                    terminology=terminology,
                    instructions=saved,
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
            project.rebuild_error = "The layout rebuild failed; it didn't count toward your regenerate limit"
            return_regeneration(project)
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
        return_regeneration(project)
    return len(stale)
