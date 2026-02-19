from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user
from app.database import SessionLocal
from app.models.credit import CreditWallet, CreditTransaction
from app.models.team import Team
from app.models.user import User

router = APIRouter(prefix="/subscription", tags=["subscription"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/activate")
def activate_subscription(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    team = db.query(Team).filter(Team.owner_id == current_user.id).first()
    wallet = db.query(CreditWallet).filter(CreditWallet.team_id == team.id).first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    now = datetime.utcnow()

    # 🔒 If subscription still active → block
    if wallet.subscription_expires_at and wallet.subscription_expires_at > now:
        raise HTTPException(
            status_code=400,
            detail="Subscription still active"
        )

    # ✅ Activate subscription for 30 days
    wallet.balance += wallet.monthly_allowance
    wallet.subscription_expires_at = now + timedelta(days=30)

    transaction = CreditTransaction(
        wallet_id=wallet.id,
        amount=wallet.monthly_allowance,
        type="SUBSCRIPTION_GRANT"
    )

    db.add(transaction)
    db.commit()
    db.refresh(wallet)

    return {
        "message": "Subscription activated",
        "new_balance": wallet.balance,
        "expires_at": wallet.subscription_expires_at
    }

@router.post("/change-plan")
def change_plan(
    plan: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    valid_plans = ["STARTER", "PRO", "ENTERPRISE"]

    if plan not in valid_plans:
        raise HTTPException(status_code=400, detail="Invalid plan")

    team = db.query(Team).filter(Team.owner_id == current_user.id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    wallet = db.query(CreditWallet).filter(CreditWallet.team_id == team.id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    wallet.plan_type = plan
    db.commit()
    db.refresh(wallet)

    return {
        "message": "Plan updated successfully",
        "new_plan": wallet.plan_type
    }
