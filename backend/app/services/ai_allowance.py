"""Per-document AI edit allowance: 10 edits per page credit, then 1 credit per further block of 10."""
import logging

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.credit import CreditTransaction
from app.models.project import TranslationProject
from app.models.user import User
from app.services.ai_actions import REGENERATE_LIMIT, is_staff
from app.services.credit_service import (
    CreditService,
    DuplicateTransactionError,
    InsufficientCreditsError,
    WalletNotFoundError,
)

logger = logging.getLogger(__name__)

EDITS_PER_CREDIT = 10
BLOCK_COST_CREDITS = 1
OUT_OF_EDITS = "You've used the AI edits included with this document. 1 credit adds 10 more."


def included_edits(project: TranslationProject) -> int:
    return EDITS_PER_CREDIT * max(1, project.page_count or 1)


def remaining_included(project: TranslationProject) -> int:
    return max(0, included_edits(project) - (project.ai_edits_used or 0))


def block_reference(project_id, block_index: int) -> str:
    return f"{project_id}:ai-edits:{block_index}"


def _block_of(project: TranslationProject, edit_number: int) -> int | None:
    over = edit_number - included_edits(project)
    return None if over <= 0 else (over - 1) // EDITS_PER_CREDIT


def _ensure_block_paid(db: Session, project: TranslationProject, block_index: int) -> None:
    reference = block_reference(project.id, block_index)
    if db.query(CreditTransaction.id).filter(CreditTransaction.reference_id == reference).first():
        return
    try:
        CreditService.deduct_credits(
            db=db,
            team_id=str(project.team_id),
            amount=BLOCK_COST_CREDITS,
            reference_id=reference,
        )
    except DuplicateTransactionError:
        return
    except (InsufficientCreditsError, WalletNotFoundError):
        raise HTTPException(status_code=402, detail=OUT_OF_EDITS)


def reserve_edit(db: Session, project: TranslationProject, user: User) -> None:
    """Before the model call: make sure the next edit is included or its block is paid for. Caller commits."""
    if is_staff(user):
        return
    block = _block_of(project, (project.ai_edits_used or 0) + 1)
    if block is not None:
        _ensure_block_paid(db, project, block)


def count_edit(db: Session, project: TranslationProject, user: User) -> None:
    """After a successful call, on the row-locked project. Caller commits."""
    project.ai_edits_used = (project.ai_edits_used or 0) + 1
    if is_staff(user):
        return
    block = _block_of(project, project.ai_edits_used)
    if block is None:
        return
    # A concurrent edit can land on a block reserve_edit didn't see; charge it now, never fail the finished edit.
    try:
        _ensure_block_paid(db, project, block)
    except HTTPException:
        logger.warning("AI edit block %s on project %s went unpaid", block, project.id)


def credits_charged(db: Session, project_id) -> int:
    total = (
        db.query(func.coalesce(func.sum(CreditTransaction.amount), 0))
        .filter(
            CreditTransaction.type == "USAGE",
            CreditTransaction.reference_id.like(f"{project_id}:ai-edits:%"),
        )
        .scalar()
    )
    return -int(total or 0)


def allowance(db: Session, project: TranslationProject) -> dict:
    return {
        "included": included_edits(project),
        "used": project.ai_edits_used or 0,
        "remaining_included": remaining_included(project),
        "next_block_cost_credits": BLOCK_COST_CREDITS,
        "credits_charged": credits_charged(db, project.id),
        "regenerations_used": min(project.revision_count or 0, REGENERATE_LIMIT),
        "regenerations_max": REGENERATE_LIMIT,
    }
