from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import stripe
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.credit import CreditWallet
from app.models.team import Team
from app.models.stripe_event import StripeEvent
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

    event_id = event["id"]
    event_type = event["type"]

    print("Received event:", event_type)

    # ---------------------------------------------------
    # Insert StripeEvent FIRST (DB-level idempotency)
    # ---------------------------------------------------
    try:
        db.add(StripeEvent(id=event_id, event_type=event_type))
        db.flush()  # Force DB insert immediately
    except IntegrityError:
        db.rollback()
        return {"status": "already_processed"}

    handled_events = [
        "invoice.payment_succeeded",
        "customer.subscription.deleted",
        "checkout.session.completed",
    ]

    if event_type not in handled_events:
        db.commit()
        return {"status": "ignored"}

    try:

        # ---------------------------------------------------
        # One-Time Credit Purchase
        # ---------------------------------------------------
        if event_type == "checkout.session.completed":

            session = event["data"]["object"]

            # Ensure payment actually completed
            if session.get("payment_status") != "paid":
                db.commit()
                return {"status": "ignored"}

            metadata = session.get("metadata", {})

            if metadata.get("type") != "credit_purchase":
                db.commit()
                return {"status": "ignored"}

            user_id = metadata.get("user_id")
            team_id = metadata.get("team_id")
            credits = int(metadata.get("credits", 0))

            if not user_id or not team_id or credits <= 0:
                db.commit()
                return {"status": "ignored"}

            wallet = (
                db.query(CreditWallet)
                .filter(CreditWallet.team_id == team_id)
                .with_for_update()
                .first()
            )

            if not wallet:
                raise HTTPException(status_code=500, detail="Wallet not found")

            wallet.purchased_credits += credits

            db.commit()
            print(f"Added {credits} purchased credits.")
            return {"status": "success"}

        # ---------------------------------------------------
        # Subscription Payment Success
        # ---------------------------------------------------
        if event_type == "invoice.payment_succeeded":

            invoice = event["data"]["object"]
            subscription_id = invoice.get("subscription")

            if not subscription_id:
                db.commit()
                return {"status": "ignored"}

            stripe_subscription = stripe.Subscription.retrieve(subscription_id)
            metadata = stripe_subscription.get("metadata", {})

            user_id = metadata.get("user_id")
            team_id = metadata.get("team_id")

            if not user_id or not team_id:
                db.commit()
                return {"status": "ignored"}

            user = db.query(User).filter(User.id == user_id).first()
            team = db.query(Team).filter(Team.id == team_id).first()

            if not user or not team:
                db.commit()
                return {"status": "ignored"}

            wallet = (
                db.query(CreditWallet)
                .filter(CreditWallet.team_id == team.id)
                .with_for_update()
                .first()
            )

            if not wallet:
                raise HTTPException(status_code=500, detail="Wallet not found")

            expiry_timestamp = stripe_subscription.get("current_period_end")

            if not expiry_timestamp:
                items = stripe_subscription.get("items", {}).get("data", [])
                if items:
                    expiry_timestamp = items[0].get("current_period_end")

            if not expiry_timestamp:
                db.commit()
                return {"status": "ignored"}

            expiry_date = datetime.utcfromtimestamp(expiry_timestamp)

            wallet.subscription_status = "ACTIVE"
            wallet.subscription_credits = SUBSCRIPTION_MONTHLY_CREDITS
            wallet.subscription_expires_at = expiry_date

            user.subscription_status = "ACTIVE"
            user.subscription_plan = "PRO"
            user.stripe_subscription_id = subscription_id

            db.commit()
            print("Subscription credits granted.")
            return {"status": "success"}

        # ---------------------------------------------------
        # Subscription Cancellation
        # ---------------------------------------------------
        if event_type == "customer.subscription.deleted":

            subscription = event["data"]["object"]
            metadata = subscription.get("metadata", {})

            user_id = metadata.get("user_id")
            team_id = metadata.get("team_id")

            if not user_id or not team_id:
                db.commit()
                return {"status": "ignored"}

            user = db.query(User).filter(User.id == user_id).first()
            team = db.query(Team).filter(Team.id == team_id).first()

            if user:
                user.subscription_status = "INACTIVE"
                user.subscription_plan = "BASIC"
                user.stripe_subscription_id = None

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

        db.commit()
        return {"status": "ignored"}

    except Exception:
        db.rollback()
        raise