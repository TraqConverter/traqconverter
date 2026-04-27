import logging
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["Stripe"])

stripe.api_key = settings.stripe_secret_key


# ============================================================
# PLAN CONFIG (REPLACE WITH REAL IDS)
# ============================================================
PLAN_CONFIG = {
    "price_pro": {
        "plan": "PRO",
        "credits": 30,
    },
    "price_basic": {
        "plan": "BASIC",
        "credits": 1,
    },
}


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

    logger.info(f"Stripe event: {event_type}")

    # ============================================================
    # IDEMPOTENCY
    # ============================================================
    try:
        db.add(StripeEvent(id=event_id, event_type=event_type))
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"status": "already_processed"}

    try:

        # ============================================================
        # ONE-TIME PURCHASE
        # ============================================================
        if event_type == "checkout.session.completed":

            session = event["data"]["object"]

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

            reference = f"checkout_{session.get('id')}"

            existing = db.query(StripeEvent).filter(
                StripeEvent.id == reference
            ).first()

            if existing:
                db.commit()
                return {"status": "duplicate_skipped"}

            wallet = db.query(CreditWallet)\
                .filter(CreditWallet.team_id == team_id)\
                .with_for_update()\
                .first()

            if not wallet:
                wallet = CreditWallet(
                    team_id=team_id,
                    purchased_credits=0,
                    subscription_credits=0,
                    subscription_status="INACTIVE"
                )
                db.add(wallet)
                db.flush()

            wallet.purchased_credits += credits

            db.add(StripeEvent(id=reference, event_type="credit_grant"))

            db.commit()
            logger.info(f"Added {credits} credits")
            return {"status": "success"}

        # ============================================================
        # SUBSCRIPTION PAYMENT (FIXED)
        # ============================================================
        if event_type == "invoice.payment_succeeded":

            invoice = event["data"]["object"]

            # PRIMARY SOURCE (NO API CALL)
            lines = invoice.get("lines", {}).get("data", [])

            price_id = None
            if lines:
                price_id = lines[0].get("price", {}).get("id")

            # METADATA (BEST SOURCE)
            metadata = invoice.get("metadata", {})
            user_id = metadata.get("user_id")
            team_id = metadata.get("team_id")

            subscription_id = invoice.get("subscription")

            # FALLBACK ONLY IF NEEDED
            if (not user_id or not team_id or not price_id) and subscription_id:
                try:
                    sub = stripe.Subscription.retrieve(subscription_id)

                    metadata = sub.get("metadata", {})
                    user_id = user_id or metadata.get("user_id")
                    team_id = team_id or metadata.get("team_id")

                    items = sub.get("items", {}).get("data", [])
                    if items and not price_id:
                        price_id = items[0].get("price", {}).get("id")

                except Exception as e:
                    logger.warning(f"Stripe fallback failed: {e}")

            if not user_id or not team_id or not price_id:
                db.commit()
                return {"status": "ignored"}

            user = db.query(User).filter(User.id == user_id).first()
            team = db.query(Team).filter(Team.id == team_id).first()

            if not user or not team:
                db.commit()
                return {"status": "ignored"}

            wallet = db.query(CreditWallet)\
                .filter(CreditWallet.team_id == team.id)\
                .with_for_update()\
                .first()

            if not wallet:
                wallet = CreditWallet(
                    team_id=team.id,
                    purchased_credits=0,
                    subscription_credits=0,
                    subscription_status="INACTIVE"
                )
                db.add(wallet)
                db.flush()

            plan_config = PLAN_CONFIG.get(price_id)

            if not plan_config:
                logger.warning(f"Unknown price_id: {price_id}")
                db.commit()
                return {"status": "unknown_plan"}

            expiry_timestamp = invoice.get("current_period_end")

            if not expiry_timestamp:
                expiry_timestamp = invoice.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")

            expiry_date = datetime.utcfromtimestamp(expiry_timestamp) if expiry_timestamp else None

            wallet.subscription_status = "ACTIVE"
            wallet.subscription_credits = plan_config["credits"]
            wallet.subscription_expires_at = expiry_date

            user.subscription_status = "ACTIVE"
            user.subscription_plan = plan_config["plan"]
            user.stripe_subscription_id = subscription_id

            db.commit()
            logger.info("Subscription updated")
            return {"status": "success"}

        # ============================================================
        # SUB CANCELLED
        # ============================================================
        if event_type == "customer.subscription.deleted":

            subscription = event["data"]["object"]
            metadata = subscription.get("metadata", {})

            user_id = metadata.get("user_id")
            team_id = metadata.get("team_id")

            user = db.query(User).filter(User.id == user_id).first()
            team = db.query(Team).filter(Team.id == team_id).first()

            if user:
                user.subscription_status = "INACTIVE"
                user.subscription_plan = "BASIC"
                user.stripe_subscription_id = None

            if team:
                wallet = db.query(CreditWallet)\
                    .filter(CreditWallet.team_id == team.id)\
                    .first()

                if wallet:
                    wallet.subscription_status = "INACTIVE"
                    wallet.subscription_credits = 0

            db.commit()
            return {"status": "success"}

        db.commit()
        return {"status": "ignored"}

    except Exception:
        logger.exception("Stripe webhook failed")
        db.commit()
        return {"status": "error_handled"}