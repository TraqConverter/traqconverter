from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import stripe
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.credit import CreditWallet
from app.models.team import Team
from app.config import settings

router = APIRouter(prefix="/stripe", tags=["Stripe"])

stripe.api_key = settings.stripe_secret_key

SUBSCRIPTION_MONTHLY_CREDITS = 30


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

    event_type = event["type"]
    print("Received event:", event_type)

    # ---------------------------------------------------
    # 1️⃣ Store Stripe Customer ID
    # ---------------------------------------------------
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")

        if not user_id:
            return {"status": "ignored"}

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"status": "ignored"}

        user.stripe_customer_id = session.get("customer")
        db.commit()

    # ---------------------------------------------------
    # 2️⃣ Subscription Payment Success (Grant Credits)
    # ---------------------------------------------------
    if event_type in ["invoice.paid", "invoice.payment_succeeded"]:
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        subscription_id = invoice.get("subscription")

        if not customer_id:
            return {"status": "ignored"}

        stripe_customer = stripe.Customer.retrieve(customer_id)
        customer_email = stripe_customer.get("email")

        if not customer_email:
            return {"status": "ignored"}

        user = db.query(User).filter(User.email == customer_email).first()
        if not user:
            return {"status": "ignored"}

        # 🔹 Update user billing metadata only
        user.subscription_status = "ACTIVE"
        user.subscription_plan = "PRO"
        user.stripe_customer_id = customer_id
        user.stripe_subscription_id = subscription_id

        # 🔹 Convert Stripe period end timestamp
        stripe_subscription = stripe.Subscription.retrieve(subscription_id)
        expiry_timestamp = stripe_subscription["current_period_end"]
        expiry_date = datetime.utcfromtimestamp(expiry_timestamp)

        # 🔹 Get user's team
        team = db.query(Team).filter(Team.owner_id == user.id).first()
        if not team:
            raise HTTPException(status_code=500, detail="Team not found")

        # 🔹 Lock wallet row
        wallet = (
            db.query(CreditWallet)
            .filter(CreditWallet.team_id == team.id)
            .with_for_update()
            .first()
        )

        if not wallet:
            raise HTTPException(status_code=500, detail="Credit wallet not found")

        # 🔹 Grant monthly credits (RESET, not add)
        wallet.subscription_status = "ACTIVE"
        wallet.subscription_credits = SUBSCRIPTION_MONTHLY_CREDITS
        wallet.subscription_expires_at = expiry_date

        db.commit()

        print(f"Granted {SUBSCRIPTION_MONTHLY_CREDITS} credits to {user.email}")

    # ---------------------------------------------------
    # 3️⃣ Subscription Cancellation
    # ---------------------------------------------------
    if event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")

        user = db.query(User).filter(
            User.stripe_customer_id == customer_id
        ).first()

        if user:
            user.subscription_status = "INACTIVE"
            user.subscription_plan = "BASIC"
            user.stripe_subscription_id = None

            team = db.query(Team).filter(Team.owner_id == user.id).first()
            if team:
                wallet = (
                    db.query(CreditWallet)
                    .filter(CreditWallet.team_id == team.id)
                    .with_for_update()
                    .first()
                )

                if wallet:
                    wallet.subscription_status = "INACTIVE"
                    wallet.subscription_credits = 0

            db.commit()

    return {"status": "success"}