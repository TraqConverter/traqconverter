from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.credit import CreditWallet


def get_wallet(db: Session, team_id: str) -> CreditWallet:
    wallet = (
        db.query(CreditWallet)
        .filter(CreditWallet.team_id == team_id)
        .with_for_update()
        .first()
    )

    if not wallet:
        raise HTTPException(status_code=404, detail="Credit wallet not found")

    return wallet


def get_total_credits(wallet: CreditWallet) -> int:
    return (wallet.subscription_credits or 0) + (wallet.purchased_credits or 0)