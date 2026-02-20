from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import stripe

from app.database import get_db
from app.models.user import User
from app.config import settings

router = APIRouter(prefix="/stripe", tags=["Stripe"])

stripe.api_key = settings.stripe_secret_key
print("Stripe key being used:", stripe.api_key)


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    print("Received event:", event["type"])

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        print("=== CHECKOUT SESSION DATA ===")
        print(session)

        metadata = session.get("metadata", {})
        print("Metadata:", metadata)

        user_id = metadata.get("user_id")
        print("User ID from metadata:", user_id)

        if not user_id:
            print("No user_id found in metadata")
            return {"status": "ignored"}

        user = db.query(User).filter(User.id == user_id).first()
        print("User found in DB:", user)

        if not user:
            print("User not found in database")
            return {"status": "ignored"}

        user.stripe_customer_id = session.get("customer")
        user.stripe_subscription_id = session.get("subscription")
        user.subscription_status = "active"
        user.monthly_credits = 39

        db.commit()

        print(f"Subscription activated for user {user.email}")

    return {"status": "success"}