from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user

from app.models.credit import CreditWallet, CreditTransaction
from app.models.user import User
from app.models.team import Team

router = APIRouter(
    prefix="/billing",
    tags=["Billing"]
)


# =========================================
# GET WALLET
# =========================================

@router.get("/wallet")
def get_wallet(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    # Find user's team
    team = (
        db.query(Team)
        .filter(Team.owner_id == current_user.id)
        .first()
    )

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Find wallet for the team
    wallet = (
        db.query(CreditWallet)
        .filter(CreditWallet.team_id == team.id)
        .first()
    )

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return {
        "subscription_credits": wallet.subscription_credits,
        "purchased_credits": wallet.purchased_credits,
        "total_credits": wallet.subscription_credits + wallet.purchased_credits,
        "plan_type": wallet.plan_type,
        "subscription_status": wallet.subscription_status,
        "subscription_expires_at": wallet.subscription_expires_at
    }


# =========================================
# CREDIT TRANSACTION HISTORY
# =========================================

@router.get("/transactions")
def get_transactions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    # Find user's team
    team = (
        db.query(Team)
        .filter(Team.owner_id == current_user.id)
        .first()
    )

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    transactions = (
        db.query(CreditTransaction)
        .join(CreditWallet)
        .filter(CreditWallet.team_id == team.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(100)
        .all()
    )

    return [
        {
            "id": t.id,
            "type": t.type,
            "amount": t.amount,
            "reference_id": t.reference_id,
            "created_at": t.created_at
        }
        for t in transactions
    ]