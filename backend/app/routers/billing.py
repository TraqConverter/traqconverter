from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import effective_plan

from app.models.credit import CreditWallet, CreditTransaction
from app.models.user import User
from app.models.team import Team
from app.core.plan_features import PLAN_FEATURES

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

    tier = effective_plan(db, current_user)
    features = PLAN_FEATURES.get(tier, {})

    trial_days_left = None
    if (
        (wallet.plan_type or "").upper() == "TRIAL"
        and wallet.subscription_expires_at
    ):
        delta = wallet.subscription_expires_at - datetime.utcnow()
        trial_days_left = max(0, int(delta.total_seconds() // 86400) + (1 if delta.total_seconds() > 0 else 0))

    return {
        "subscription_credits": wallet.subscription_credits,
        "purchased_credits": wallet.purchased_credits,
        "total_credits": wallet.subscription_credits + wallet.purchased_credits,
        "plan_type": wallet.plan_type,
        "subscription_status": wallet.subscription_status,
        "subscription_expires_at": wallet.subscription_expires_at,
        # Resolved tier the rest of the app should gate on. TRIAL/BASIC/PRO/EXPIRED.
        "tier": tier,
        # Per-feature flags so the frontend can show or hide nav entries / CTAs
        # without re-implementing the rules.
        "features": features,
        # When on TRIAL, how many whole days are left before the wallet expires.
        "trial_days_left": trial_days_left,
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