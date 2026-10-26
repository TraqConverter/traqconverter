"""Per-document AI edit allowance: AI_EDITS_PER_PAGE edits per page, then 1 credit per further block of AI_EDITS_PER_EXTRA_CREDIT."""
import logging

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.credit import CreditTransaction
from app.models.project import TranslationProject
from app.models.user import User
from app.services import ai_actions
from app.services.ai_actions import is_staff
from app.services.credit_service import (
    CreditService,
    DuplicateTransactionError,
    InsufficientCreditsError,
    WalletNotFoundError,
)

logger = logging.getLogger(__name__)

BLOCK_COST_CREDITS = 1


def edits_per_block() -> int:
    return max(1, settings.AI_EDITS_PER_EXTRA_CREDIT)


def out_of_edits_message() -> str:
    return f"You've used the AI edits included with this document. 1 credit adds {edits_per_block()} more."


def included_edits(project: TranslationProject) -> int:
    return settings.AI_EDITS_PER_PAGE * max(1, project.page_count or 1)


def remaining_included(project: TranslationProject) -> int:
    return max(0, included_edits(project) - (project.ai_edits_used or 0))


def block_reference(project_id, block_index: int) -> str:
    return f"{project_id}:ai-edits:{block_index}"


def _block_of(project: TranslationProject, edit_number: int) -> int | None:
    over = edit_number - included_edits(project)
    return None if over <= 0 else (over - 1) // edits_per_block()


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
        raise HTTPException(status_code=402, detail=out_of_edits_message())


def _blocks_between(project: TranslationProject, first: int, last: int) -> list[int]:
    return sorted({b for n in range(first, last + 1) if (b := _block_of(project, n)) is not None})


def reserve_edit(db: Session, project: TranslationProject, user: User, count: int = 1) -> None:
    """Before the model call: make sure the next `count` edits are included or their blocks are paid for. Caller commits."""
    if is_staff(user):
        return
    used = project.ai_edits_used or 0
    for block in _blocks_between(project, used + 1, used + count):
        _ensure_block_paid(db, project, block)


def count_edit(db: Session, project: TranslationProject, user: User, count: int = 1) -> None:
    """After a successful call, on the row-locked project. Caller commits."""
    before = project.ai_edits_used or 0
    project.ai_edits_used = before + count
    if is_staff(user):
        return
    # A concurrent edit can land on a block reserve_edit didn't see; charge it now, never fail the finished edit.
    for block in _blocks_between(project, before + 1, project.ai_edits_used):
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


def allowance(db: Session, project: TranslationProject, user: User | None = None) -> dict:
    return {
        "included": included_edits(project),
        "used": project.ai_edits_used or 0,
        "remaining_included": remaining_included(project),
        "next_block_cost_credits": BLOCK_COST_CREDITS,
        "edits_per_extra_credit": edits_per_block(),
        "credits_charged": credits_charged(db, project.id),
        "regenerations_used": min(project.revision_count or 0, ai_actions.regenerate_limit()),
        "regenerations_max": ai_actions.regenerate_limit(),
        "regenerations_free": settings.REGENERATE_FREE_PER_PROJECT,
        "next_regenerate_cost_credits": ai_actions.next_regenerate_cost(project, user),
    }
