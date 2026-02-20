from datetime import datetime
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
    wallet = (
        db.query(CreditWallet)
        .filter(CreditWallet.team_id == team_id)
        .with_for_update()
        .first()
    )

    if not wallet:
        raise HTTPException(status_code=404, detail="Credit wallet not found")

    now = datetime.utcnow()

    # 🔒 If subscription expired, zero out subscription credits usage
    if (
        wallet.subscription_status == "ACTIVE"
        and wallet.subscription_expires_at
        and wallet.subscription_expires_at < now
    ):
        wallet.subscription_status = "EXPIRED"
        wallet.subscription_credits = 0

    # 🔹 Calculate total available credits
    total_available = wallet.subscription_credits + wallet.purchased_credits

    if total_available < page_count:
        raise HTTPException(status_code=400, detail="Insufficient credits")

    remaining = page_count

    # 🔹 Deduct subscription credits first (only if ACTIVE)
    if wallet.subscription_status == "ACTIVE":
        if wallet.subscription_credits >= remaining:
            wallet.subscription_credits -= remaining
            remaining = 0
        else:
            remaining -= wallet.subscription_credits
            wallet.subscription_credits = 0

    # 🔹 Deduct remaining from purchased credits
    if remaining > 0:
        wallet.purchased_credits -= remaining

    # 🔹 Log transaction
    transaction = CreditTransaction(
        wallet_id=wallet.id,
        type="USAGE",
        amount=-page_count,
    )
    db.add(transaction)

    # 🔹 Create job
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

    db.commit()
    db.refresh(job)

    return job