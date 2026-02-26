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


@router.post("/create-checkout-session")
def create_checkout_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 🔹 Resolve user's team
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
                "price": "price_1T2zQcJMRLn8RrZKlyp9gtxe",
                "quantity": 1,
            }
        ],
        success_url="http://localhost:3000/success",
        cancel_url="http://localhost:3000/cancel",

        # 🔹 Attach metadata to checkout session
        metadata={
            "user_id": str(current_user.id),
            "team_id": str(team.id),
        },

        # 🔹 CRITICAL: Attach metadata to subscription itself
        subscription_data={
            "metadata": {
                "user_id": str(current_user.id),
                "team_id": str(team.id),
            }
        }
    )

    return {"checkout_url": session.url}

@router.post("/purchase-credits")
def purchase_credits(
    amount: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Basic validation
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid credit amount")

    # Example pricing logic: $1 per credit
    unit_price_cents = 100
    total_price_cents = amount * unit_price_cents

    # Get team
    team = db.query(Team).filter(Team.owner_id == current_user.id).first()
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
        success_url="http://localhost:3000/success",
        cancel_url="http://localhost:3000/cancel",
        metadata={
            "type": "credit_purchase",
            "user_id": str(current_user.id),
            "team_id": str(team.id),
            "credits": str(amount),
        },
    )

    return {"checkout_url": session.url}