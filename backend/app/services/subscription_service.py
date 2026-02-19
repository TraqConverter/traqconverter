from sqlalchemy.orm import Session
from app.models.credit import CreditWallet, CreditTransaction
from app.models.team import Team
from uuid import uuid4


def grant_monthly_credits(db: Session, team_id: str, amount: int = 39):
    wallet = db.query(CreditWallet).filter(CreditWallet.team_id == team_id).first()

    if not wallet:
        raise Exception("Wallet not found")

    wallet.balance += amount

    transaction = CreditTransaction(
        id=uuid4(),
        wallet_id=wallet.id,
        type="SUBSCRIPTION_GRANT",
        amount=amount
    )

    db.add(transaction)
    db.commit()
    db.refresh(wallet)

    return wallet.balance
