from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.credit import CreditWallet, CreditTransaction


def deduct_credits(db: Session, team_id, pages: int):
    wallet = db.query(CreditWallet).filter(
        CreditWallet.team_id == team_id
    ).first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Credit wallet not found")

    if wallet.balance < pages:
        raise HTTPException(status_code=400, detail="Insufficient credits")

    wallet.balance -= pages

    transaction = CreditTransaction(
        wallet_id=wallet.id,
        type="USAGE",
        amount=-pages
    )

    db.add(transaction)
    db.commit()
    db.refresh(wallet)

    return wallet.balance
