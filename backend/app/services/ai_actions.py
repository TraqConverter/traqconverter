"""Billing, locking and background execution for user-triggered AI work on an existing project."""
import logging
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.credit import CreditTransaction
from app.models.project import TranslationProject, is_dtp
from app.core.roles import is_staff
from app.models.user import User
from app.services.credit_service import (
    CreditService,
    DuplicateTransactionError,
    InsufficientCreditsError,
    WalletNotFoundError,
)

logger = logging.getLogger(__name__)

REBUILD_LOCK_MINUTES = 30
# Regenerate re-authors the layout from page images, so it needs a PDF or an image source.
REGENERABLE_KINDS = ("PDF", "IMAGE")


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


def regenerate_limit() -> int:
    return settings.REGENERATE_LIMIT_PER_PROJECT


def regenerations_left(project: TranslationProject) -> int:
    return max(0, regenerate_limit() - (project.revision_count or 0))


def next_regenerate_cost(project: TranslationProject, user: User | None = None) -> int:
    """Credits the next regenerate costs: free for the first ones and for staff, then one per page."""
    if user is not None and is_staff(user):
        return 0
    if (project.revision_count or 0) < settings.REGENERATE_FREE_PER_PROJECT:
        return 0
    return max(1, project.page_count or 1)


def regenerate_costs_message(cost: int) -> str:
    unit = "credit" if cost == 1 else "credits"
    return f"Regenerating again costs {cost} {unit} (one per page). Add credits in Billing."


def _regenerate_charges(db: Session, project_id):
    return db.query(CreditTransaction).filter(
        CreditTransaction.type == "USAGE",
        CreditTransaction.reference_id.like(f"regenerate:{project_id}:%"),
    )


def use_regeneration(db: Session, project: TranslationProject, user: User) -> int:
    """Count a regenerate against the per-document cap and charge it when it isn't free. Caller commits."""
    if regenerations_left(project) <= 0:
        raise HTTPException(status_code=403, detail=f"Regenerate is limited to {regenerate_limit()} per document")
    cost = next_regenerate_cost(project, user)
    if cost:
        attempt = _regenerate_charges(db, project.id).count() + 1
        try:
            CreditService.deduct_credits(
                db=db,
                team_id=str(project.team_id),
                amount=cost,
                reference_id=f"regenerate:{project.id}:{attempt}",
            )
        except (InsufficientCreditsError, WalletNotFoundError):
            raise HTTPException(status_code=402, detail=regenerate_costs_message(cost))
        except DuplicateTransactionError:
            raise HTTPException(status_code=409, detail="A regenerate is already starting for this document")
    project.revision_count = (project.revision_count or 0) + 1
    return cost


def return_regeneration(db: Session, project: TranslationProject) -> None:
    """A failed attempt doesn't count against the cap, and its charge, if any, is refunded. Caller commits."""
    project.revision_count = max(0, (project.revision_count or 0) - 1)
    started = project.rebuild_started_at
    if not started:
        return
    # The running attempt's charge is the newest one, made just before the rebuild was claimed.
    latest = (
        _regenerate_charges(db, project.id)
        .filter(CreditTransaction.created_at >= started - timedelta(minutes=1))
        .order_by(CreditTransaction.created_at.desc())
        .first()
    )
    if latest:
        CreditService.refund_usage(db, latest.reference_id)


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
            if (project.source_kind or "").upper() == "IMAGE":
                from app.services.translation_processor import _image_to_pdf

                pdf_bytes = _image_to_pdf(pdf_bytes, project.file_name or "")
            from app.services.learning import source_text_of, team_terminology
            from app.services.translation_memory_service import with_memory

            dtp = is_dtp(project)
            source_lang = project.target_language if dtp else project.source_language
            if dtp:
                terminology, saved = "", ""
            else:
                source_text = source_text_of(db, project)
                terminology = with_memory(db, project, team_terminology(db, project, source_text), source_text)
                saved = project.ai_instructions or ""
            if instructions:
                from app.services.claude_multiturn_rebuild import author_rebuild_docx_multiturn

                docx_bytes = author_rebuild_docx_multiturn(
                    pdf_bytes,
                    source_lang or "",
                    project.target_language or "",
                    extra_instructions=instructions,
                    terminology=terminology,
                    instructions=saved,
                    reproduce=dtp,
                )
            else:
                from app.services.claude_authored_rebuild import author_rebuild_docx

                docx_bytes = author_rebuild_docx(
                    pdf_bytes=pdf_bytes,
                    source_lang=source_lang or "",
                    target_lang=project.target_language or "",
                    terminology=terminology,
                    instructions=saved,
                    reproduce=dtp,
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
            project.rebuild_error = "The layout rebuild failed; it didn't count toward your regenerate limit, and any credits it used were refunded"
            return_regeneration(db, project)
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
        return_regeneration(db, project)
    return len(stale)
