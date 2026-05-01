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
from app.core.plan_features import SUBSCRIPTION_GRANTS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["Stripe"])

stripe.api_key = settings.stripe_secret_key


# ============================================================
# PLAN CONFIG — keys are the real Stripe price IDs (from .env), values
# describe the wallet update we should apply when an invoice for that
# price is paid. Credit grants come from a single source of truth in
# app.core.plan_features.SUBSCRIPTION_GRANTS.
# ============================================================
def _build_plan_config():
    cfg = {}
    if getattr(settings, "STRIPE_PRICE_BASIC", None):
        cfg[settings.STRIPE_PRICE_BASIC] = {
            "plan": "BASIC",
            "credits": SUBSCRIPTION_GRANTS["BASIC"],
        }
    if getattr(settings, "STRIPE_PRICE_PRO", None):
        cfg[settings.STRIPE_PRICE_PRO] = {
            "plan": "PRO",
            "credits": SUBSCRIPTION_GRANTS["PRO"],
        }
    return cfg


PLAN_CONFIG = _build_plan_config()


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
            mode = session.get("mode")
            user_id = metadata.get("user_id")
            team_id = metadata.get("team_id")

            # ----------------------------------------------------------------
            # ONE-TIME CREDIT TOP-UP
            # ----------------------------------------------------------------
            if metadata.get("type") == "credit_purchase":
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

            # ----------------------------------------------------------------
            # SUBSCRIPTION CHECKOUT — flip wallet to BASIC/PRO immediately
            # using the `plan` metadata we set in create_checkout_session.
            # This way the upgrade lands as soon as the user pays, without
            # waiting for invoice.payment_succeeded and without depending
            # on .env price IDs being correct.
            # ----------------------------------------------------------------
            if mode == "subscription" or metadata.get("plan"):
                from app.core.plan_features import SUBSCRIPTION_GRANTS

                plan = (metadata.get("plan") or "").upper()
                if plan not in SUBSCRIPTION_GRANTS:
                    logger.warning(f"Unknown plan in subscription session: {plan}")
                    db.commit()
                    return {"status": "unknown_plan"}

                if not user_id or not team_id:
                    db.commit()
                    return {"status": "ignored"}

                reference = f"sub_checkout_{session.get('id')}"
                existing = db.query(StripeEvent).filter(
                    StripeEvent.id == reference
                ).first()
                if existing:
                    db.commit()
                    return {"status": "duplicate_skipped"}

                wallet = (
                    db.query(CreditWallet)
                    .filter(CreditWallet.team_id == team_id)
                    .with_for_update()
                    .first()
                )
                if not wallet:
                    wallet = CreditWallet(
                        team_id=team_id,
                        purchased_credits=0,
                        subscription_credits=0,
                        subscription_status="INACTIVE",
                    )
                    db.add(wallet)
                    db.flush()

                wallet.plan_type = plan
                wallet.subscription_status = "ACTIVE"
                wallet.subscription_credits = SUBSCRIPTION_GRANTS[plan]
                # subscription_expires_at gets set precisely by the invoice
                # event; for now mark it as "no expiry yet" so feature_guard
                # treats the user as ACTIVE (it doesn't check this for paid
                # plans, only for trials).
                wallet.subscription_expires_at = None

                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    user.subscription_status = "ACTIVE"
                    user.subscription_plan = plan
                    user.stripe_subscription_id = session.get("subscription")

                db.add(StripeEvent(id=reference, event_type="subscription_grant"))
                db.commit()
                logger.info(f"Subscription activated: {plan}")
                return {"status": "success"}

            db.commit()
            return {"status": "ignored"}

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
            # IMPORTANT: bump wallet.plan_type too — this is what the
            # feature_guard reads to resolve the user's effective tier.
            # Forgetting this leaves the user on TRIAL forever.
            wallet.plan_type = plan_config["plan"]

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
                user.subscription_plan = "EXPIRED"
                user.stripe_subscription_id = None

            if team:
                wallet = db.query(CreditWallet)\
                    .filter(CreditWallet.team_id == team.id)\
                    .first()

                if wallet:
                    wallet.subscription_status = "INACTIVE"
                    wallet.subscription_credits = 0
                    # Drop the wallet's plan_type back so feature_guard
                    # treats them as EXPIRED (gates re-engage immediately).
                    wallet.plan_type = "EXPIRED"

            db.commit()
            return {"status": "success"}

        db.commit()
        return {"status": "ignored"}

    except Exception:
        logger.exception("Stripe webhook failed")
        db.commit()
        return {"status": "error_handled"}
