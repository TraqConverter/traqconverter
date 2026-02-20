from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import stripe

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.config import settings

router = APIRouter(prefix="/subscription", tags=["subscription"])

stripe.api_key = settings.stripe_secret_key


@router.post("/create-checkout-session")
def create_checkout_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        metadata={
            "user_id": str(current_user.id)
        }
    )

    return {"checkout_url": session.url}