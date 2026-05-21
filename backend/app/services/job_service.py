from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.job import Job
from app.services.credit_service import (
    CreditService,
    WalletNotFoundError,
    InsufficientCreditsError,
)


def create_translation_job(
    db: Session,
    team_id,
    user_id,
    source_language: str,
    target_language: str,
    page_count: int,
):
    """
     FIXED:
    - All credit logic delegated to CreditService
    - No duplication
    - Single source of truth
    """

    try:
        # CENTRALIZED CREDIT DEDUCTION
        CreditService.deduct_credits(
            db=db,
            team_id=team_id,
            amount=page_count,
            reference_id=f"job_{user_id}_{datetime.utcnow().timestamp()}",
        )

    except WalletNotFoundError:
        raise HTTPException(status_code=404, detail="Credit wallet not found")

    except InsufficientCreditsError:
        raise HTTPException(status_code=400, detail="Insufficient credits")

    # ============================================================
    # CREATE JOB
    # ============================================================
    job = Job(
        team_id=team_id,
        created_by=user_id,
        source_language=source_language,
        target_language=target_language,
        page_count=page_count,
        credits_used=page_count,
        status="TRANSLATING",
    )

    db.add(job)

    # COMMIT ONCE (important)
    db.commit()
    db.refresh(job)

    return job