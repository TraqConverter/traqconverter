from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.credit import CreditWallet, CreditTransaction


def deduct_wallet_credits(db: Session, team_id: str, pages: int):

    wallet = (
        db.query(CreditWallet)
        .filter(CreditWallet.team_id == team_id)
        .with_for_update()
        .first()
    )

    if not wallet:
        raise HTTPException(status_code=404, detail="Credit wallet not found")

    total_available = wallet.subscription_credits + wallet.purchased_credits

    if total_available < pages:
        raise HTTPException(status_code=400, detail="Insufficient credits")

    remaining = pages

    # Deduct subscription credits first
    if wallet.subscription_credits >= remaining:
        wallet.subscription_credits -= remaining
        remaining = 0
    else:
        remaining -= wallet.subscription_credits
        wallet.subscription_credits = 0

    # Deduct purchased credits
    if remaining > 0:
        wallet.purchased_credits -= remaining

    # Log transaction
    transaction = CreditTransaction(
        wallet_id=wallet.id,
        type="USAGE",
        amount=-pages,
    )

    db.add(transaction)

    return (
        wallet.subscription_credits + wallet.purchased_credits
    )