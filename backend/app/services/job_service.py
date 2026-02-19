from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.job import Job
from app.models.credit import CreditWallet, CreditTransaction


def create_translation_job(
    db: Session,
    team_id,
    user_id,
    source_language: str,
    target_language: str,
    page_count: int,
):
    wallet = db.query(CreditWallet).filter(
        CreditWallet.team_id == team_id
    ).with_for_update().first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Credit wallet not found")

    if wallet.balance < page_count:
        raise HTTPException(status_code=400, detail="Insufficient credits")

    # Deduct credits
    wallet.balance -= page_count

    transaction = CreditTransaction(
        wallet_id=wallet.id,
        type="USAGE",
        amount=-page_count
    )
    db.add(transaction)

    # Create job
    job = Job(
        team_id=team_id,
        created_by=user_id,
        source_language=source_language,
        target_language=target_language,
        page_count=page_count,
        credits_used=page_count,
        status="TRANSLATING"
    )

    db.add(job)

    db.commit()
    db.refresh(job)

    return job
