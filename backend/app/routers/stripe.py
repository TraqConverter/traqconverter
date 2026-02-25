from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
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
    # 🔒 Idempotency check
    # ---------------------------------------------------
    existing_event = db.query(StripeEvent).filter(
        StripeEvent.id == event_id
    ).first()

    if existing_event:
        print("Duplicate event ignored:", event_id)
        return {"status": "already_processed"}

    # ---------------------------------------------------
    # Only process specific events
    # ---------------------------------------------------
    handled_events = [
    "invoice.payment_succeeded",
    "customer.subscription.deleted",
]

    if event_type not in handled_events:
        return {"status": "ignored"}

    # ---------------------------------------------------
    # Handle Subscription Payment Success
    # ---------------------------------------------------
    if event_type == "invoice.payment_succeeded":

        invoice = event["data"]["object"]
        subscription_id = invoice.get("subscription")

        if not subscription_id:
            return {"status": "ignored"}

        # Retrieve subscription safely
        try:
            stripe_subscription = stripe.Subscription.retrieve(subscription_id)
        except Exception as e:
            print("Failed to retrieve subscription:", str(e))
            return {"status": "ignored"}

        metadata = stripe_subscription.get("metadata", {})

        user_id = metadata.get("user_id")
        team_id = metadata.get("team_id")

        if not user_id or not team_id:
            print("Missing subscription metadata — ignoring")
            return {"status": "ignored"}

        user = db.query(User).filter(User.id == user_id).first()
        team = db.query(Team).filter(Team.id == team_id).first()

        if not user or not team:
            return {"status": "ignored"}

        wallet = (
            db.query(CreditWallet)
            .filter(CreditWallet.team_id == team.id)
            .with_for_update()
            .first()
        )

        if not wallet:
            raise HTTPException(status_code=500, detail="Wallet not found")

        # ✅ SAFE expiry handling
        expiry_timestamp = stripe_subscription.get("current_period_end")

        if not expiry_timestamp:
            items = stripe_subscription.get("items", {}).get("data", [])
            if items:
                expiry_timestamp = items[0].get("current_period_end")

        if not expiry_timestamp:
            print("Could not determine subscription expiry")
            return {"status": "ignored"}

        expiry_date = datetime.utcfromtimestamp(expiry_timestamp)

        wallet.subscription_status = "ACTIVE"
        wallet.subscription_credits = SUBSCRIPTION_MONTHLY_CREDITS
        wallet.subscription_expires_at = expiry_date

        user.subscription_status = "ACTIVE"
        user.subscription_plan = "PRO"
        user.stripe_subscription_id = subscription_id

        db.add(StripeEvent(id=event_id, event_type=event_type))
        db.commit()

        print("Credits granted safely.")

        return {"status": "success"}

    # ---------------------------------------------------
    # Handle Cancellation
    # ---------------------------------------------------
    if event_type == "customer.subscription.deleted":

        subscription = event["data"]["object"]
        metadata = subscription.get("metadata", {})

        user_id = metadata.get("user_id")
        team_id = metadata.get("team_id")

        if not user_id or not team_id:
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

        db.add(StripeEvent(id=event_id, event_type=event_type))
        db.commit()

        return {"status": "success"}

    return {"status": "ignored"}