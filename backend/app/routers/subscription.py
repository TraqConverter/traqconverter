from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import stripe

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.team import Team
from app.config import settings

router = APIRouter(prefix="/subscription", tags=["subscription"])

stripe.api_key = settings.stripe_secret_key


# ============================================================
#  PLAN CONFIG (ENV-DRIVEN)
# ============================================================
PLAN_PRICE_MAP = {
    "PRO": settings.STRIPE_PRICE_PRO,       # e.g. price_123
    "BASIC": settings.STRIPE_PRICE_BASIC,   # optional
}


# ============================================================
# CREATE SUBSCRIPTION CHECKOUT
# ============================================================
@router.post("/create-checkout-session")
def create_checkout_session(
    plan: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
     FIXED:
    - No hardcoded price IDs
    - Plan-based mapping
    - Environment configurable
    """

    # Validate plan
    price_id = PLAN_PRICE_MAP.get(plan.upper())
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan")

    # Resolve team
    team = db.query(Team).filter(
        Team.owner_id == current_user.id
    ).first()

    if not team:
        raise HTTPException(status_code=400, detail="Team not found")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        success_url=settings.STRIPE_SUCCESS_URL,
        cancel_url=settings.STRIPE_CANCEL_URL,

        # 🔹 Attach metadata to checkout session
        metadata={
            "user_id": str(current_user.id),
            "team_id": str(team.id),
            "plan": plan.upper(),
        },

        # 🔹 Attach metadata to subscription
        subscription_data={
            "metadata": {
                "user_id": str(current_user.id),
                "team_id": str(team.id),
                "plan": plan.upper(),
            }
        }
    )

    return {"checkout_url": session.url}


# ============================================================
# ONE-TIME CREDIT PURCHASE
# ============================================================
@router.post("/purchase-credits")
def purchase_credits(
    amount: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
 FIXED:
    - No hardcoded URLs
    - Config-driven pricing possible
    """

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid credit amount")

    # Pricing (move to config later if needed)
    unit_price_cents = settings.CREDIT_PRICE_CENTS  # e.g. 100
    total_price_cents = amount * unit_price_cents

    team = db.query(Team).filter(
        Team.owner_id == current_user.id
    ).first()

    if not team:
        raise HTTPException(status_code=400, detail="Team not found")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{amount} Translation Credits",
                    },
                    "unit_amount": total_price_cents,
                },
                "quantity": 1,
            }
        ],
        success_url=settings.STRIPE_SUCCESS_URL,
        cancel_url=settings.STRIPE_CANCEL_URL,
        metadata={
            "type": "credit_purchase",
            "user_id": str(current_user.id),
            "team_id": str(team.id),
            "credits": str(amount),
        },
    )

    return {"checkout_url": session.url}