import logging
import uuid
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import stripe
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.credit import CreditTransaction, CreditWallet
from app.models.stripe_event import StripeEvent
from app.config import settings
from app.core.plan_features import PAID_PLANS, SUBSCRIPTION_GRANTS, price_lookup_key
from app.routers.subscription import plan_price_id
from app.services.stripe_billing import (
    is_current_subscription,
    stripe_id,
    team_for_subscription,
    team_users,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe", tags=["Stripe"])

stripe.api_key = settings.stripe_secret_key



stripe.max_network_retries = 3








def _build_plan_config():
    cfg = {}
    for plan in PAID_PLANS:
        price_id = plan_price_id(plan)
        if price_id:
            cfg[price_id] = {"plan": plan, "credits": SUBSCRIPTION_GRANTS[plan]}
    return cfg


PLAN_CONFIG = _build_plan_config()


def _plan_for_price(price):
    """A paid plan for a Stripe price (id or object): the configured price ids, then the setup script's lookup_key."""
    price_id = stripe_id(price)
    cfg = PLAN_CONFIG.get(price_id)
    if cfg:
        return cfg["plan"]
    lookup_key = price.get("lookup_key") if isinstance(price, dict) else None
    if lookup_key:
        return next((p for p in PAID_PLANS if price_lookup_key(p) == lookup_key), None)
    return None


def _line_price_id(line):
    price = line.get("price")
    if price:
        return stripe_id(price)
    # API versions from 2025-03-31 move the price under pricing.price_details.
    return ((line.get("pricing") or {}).get("price_details") or {}).get("price")


def _is_proration(line):
    if line.get("proration"):
        return True
    parent = line.get("parent") or {}
    details = parent.get("subscription_item_details") or parent.get("invoice_item_details") or {}
    return bool(details.get("proration"))


def _invoice_plan_line(invoice):
    """The line that bills the plan: a renewal after a plan change also carries proration lines for the old price."""
    lines = (invoice.get("lines") or {}).get("data") or []
    regular = [line for line in lines if not _is_proration(line)]
    return (regular or lines or [{}])[0]


def _invoice_subscription_id(invoice):
    sub = invoice.get("subscription")
    if not sub:
        parent = invoice.get("parent") or {}
        sub = (parent.get("subscription_details") or {}).get("subscription")
    return stripe_id(sub)


def _subscription_item(sub):
    items = (sub.get("items") or {}).get("data") or []
    return items[0] if items else {}


def _subscription_period(sub, field):
    # API versions from 2025-03-31 keep the billing period on the item, not the subscription.
    return sub.get(field) or _subscription_item(sub).get(field)


def _utc(ts):
    return datetime.utcfromtimestamp(ts) if ts else None


def _plan_for_invoice_price(price, price_id):
    """_plan_for_price, asking Stripe for the price's lookup_key when the invoice only names its id."""
    plan = _plan_for_price(price if isinstance(price, dict) else price_id)
    if plan or not price_id:
        return plan
    # Raises when Stripe can't be reached, so the webhook fails and Stripe retries it.
    return _plan_for_price(stripe.Price.retrieve(price_id))


def _record_grant(db: Session, wallet, kind: str, amount: int, reference: str):
    """A ledger row for credits Stripe paid for, so they show in the wallet history."""
    db.add(CreditTransaction(wallet_id=wallet.id, type=kind, amount=amount, reference_id=reference))


def _locked_wallet(db: Session, team_id):
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
    return wallet


def _subscription_users(db: Session, team, subscription_id, user_id):
    """Users holding this subscription, plus the one who checked out."""
    users = [u for u in team_users(db, team) if u.stripe_subscription_id == subscription_id] if team else []
    if user_id and not any(str(u.id) == str(user_id) for u in users):
        try:
            extra = db.query(User).filter(User.id == uuid.UUID(str(user_id))).first()
        except ValueError:
            extra = None
        if extra:
            users.append(extra)
    return users


def _handle_subscription_updated(db: Session, event):
    sub = event["data"]["object"]
    previous = event["data"].get("previous_attributes") or {}
    sub_id = sub.get("id")
    customer_id = stripe_id(sub.get("customer"))
    metadata = sub.get("metadata") or {}

    team = team_for_subscription(db, metadata.get("team_id"), customer_id, sub_id)
    if not team:
        db.commit()
        return {"status": "ignored"}
    if not is_current_subscription(db, team, sub_id):
        logger.warning(f"Update for subscription {sub_id} that team {team.id} doesn't pay through")
        db.commit()
        return {"status": "ignored"}

    status = (sub.get("status") or "").lower()
    if status in ("incomplete", "incomplete_expired"):
        db.commit()
        return {"status": "ignored"}

    item = _subscription_item(sub)
    plan = _plan_for_price(item.get("price") or {})
    if not plan:
        logger.warning(f"Unknown price on subscription {sub_id}: {stripe_id(item.get('price'))}")
        db.commit()
        return {"status": "unknown_plan"}

    wallet = _locked_wallet(db, team.id)
    users = _subscription_users(db, team, sub_id, metadata.get("user_id"))
    for user in users:
        if customer_id:
            user.stripe_customer_id = customer_id

    if status in ("canceled", "unpaid"):
        wallet.subscription_status = "INACTIVE"
        for user in users:
            user.subscription_status = "INACTIVE"
        db.commit()
        return {"status": "inactive"}

    old_plan = (wallet.plan_type or "").upper()
    was_paying = old_plan in PAID_PLANS and (wallet.subscription_status or "").upper() == "ACTIVE"
    previous_items = (previous.get("items") or {}).get("data") or []
    previous_price = previous_items[0].get("price") if previous_items else None
    if previous_price:
        old_plan = _plan_for_price(previous_price) or old_plan
    new_price_id = stripe_id(item.get("price"))
    old_price_id = stripe_id(previous_price) or plan_price_id(old_plan) or old_plan

    wallet.plan_type = plan
    wallet.subscription_status = "ACTIVE"
    period_end = _utc(_subscription_period(sub, "current_period_end"))
    if period_end:
        wallet.subscription_expires_at = period_end
    for user in users:
        user.subscription_status = "ACTIVE"
        user.subscription_plan = plan
        user.stripe_subscription_id = sub_id

    result = "success"
    old_credits = SUBSCRIPTION_GRANTS.get(old_plan) if was_paying else None
    new_credits = SUBSCRIPTION_GRANTS[plan]
    if old_credits is not None and new_credits > old_credits:
        # One top-up per subscription, price change and billing period, however often Stripe resends it.
        period_start = _subscription_period(sub, "current_period_start") or ""
        reference = f"sub_upgrade_{sub_id}_{old_price_id}_{new_price_id}_{period_start}"
        if not db.query(StripeEvent).filter(StripeEvent.id == reference).first():
            top_up = new_credits - old_credits
            wallet.subscription_credits = (wallet.subscription_credits or 0) + top_up
            db.add(CreditTransaction(
                wallet_id=wallet.id,
                type="SUBSCRIPTION_GRANT",
                amount=top_up,
                reference_id=reference,
            ))
            db.add(StripeEvent(id=reference, event_type="subscription_upgrade"))
            logger.info(f"Upgrade {old_plan} -> {plan} for team {team.id}: +{top_up} credits")
        result = "upgraded"
    elif old_credits is not None and new_credits < old_credits:
        # Credits already granted this period stay; the renewal invoice grants the smaller allowance.
        logger.info(f"Downgrade {old_plan} -> {plan} for team {team.id}")
        result = "downgraded"

    db.commit()
    return {"status": result}


def _handle_subscription_deleted(db: Session, event):
    sub = event["data"]["object"]
    sub_id = sub.get("id")
    metadata = sub.get("metadata") or {}
    team = team_for_subscription(
        db, metadata.get("team_id"), stripe_id(sub.get("customer")), sub_id
    )
    if team and not is_current_subscription(db, team, sub_id):
        # Ending a stray second subscription must not end the plan the team still pays for.
        logger.warning(f"Deleted subscription {sub_id} isn't team {team.id}'s current one")
        db.commit()
        return {"status": "ignored"}

    for user in _subscription_users(db, team, sub_id, metadata.get("user_id")):
        user.subscription_status = "INACTIVE"
        user.subscription_plan = "EXPIRED"
        user.stripe_subscription_id = None

    if team:
        wallet = db.query(CreditWallet).filter(CreditWallet.team_id == team.id).first()
        if wallet:
            wallet.subscription_status = "INACTIVE"
            wallet.subscription_credits = 0
            wallet.plan_type = "EXPIRED"
            wallet.subscription_expires_at = _utc(sub.get("ended_at")) or datetime.utcnow()

    db.commit()
    return {"status": "success"}


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
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    event_id = event["id"]
    event_type = event["type"]

    logger.info(f"Stripe event: {event_type}")




    try:
        db.add(StripeEvent(id=event_id, event_type=event_type))
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"status": "already_processed"}

    try:




        if event_type == "checkout.session.completed":

            session = event["data"]["object"]

            if session.get("payment_status") != "paid":
                db.commit()
                return {"status": "ignored"}

            metadata = session.get("metadata", {})
            mode = session.get("mode")
            user_id = metadata.get("user_id")
            team_id = metadata.get("team_id")




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
                _record_grant(db, wallet, "PURCHASE", credits, reference)

                db.add(StripeEvent(id=reference, event_type="credit_grant"))

                db.commit()
                logger.info(f"Added {credits} credits")
                return {"status": "success"}








            if mode == "subscription" or metadata.get("plan"):
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




                wallet.subscription_expires_at = None
                _record_grant(db, wallet, "SUBSCRIPTION_GRANT", SUBSCRIPTION_GRANTS[plan], reference)

                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    user.subscription_status = "ACTIVE"
                    user.subscription_plan = plan
                    user.stripe_subscription_id = stripe_id(session.get("subscription"))
                    user.stripe_customer_id = stripe_id(session.get("customer")) or user.stripe_customer_id

                db.add(StripeEvent(id=reference, event_type="subscription_grant"))
                db.commit()
                logger.info(f"Subscription activated: {plan}")
                return {"status": "success"}

            db.commit()
            return {"status": "ignored"}




        if event_type == "invoice.payment_succeeded":

            invoice = event["data"]["object"]


            plan_line = _invoice_plan_line(invoice)
            price_id = _line_price_id(plan_line)
            price = plan_line.get("price") or price_id


            metadata = invoice.get("metadata", {})
            user_id = metadata.get("user_id")
            team_id = metadata.get("team_id")

            subscription_id = _invoice_subscription_id(invoice)


            if (not user_id or not team_id or not price_id) and subscription_id:
                try:
                    sub = stripe.Subscription.retrieve(subscription_id)

                    metadata = sub.get("metadata", {})
                    user_id = user_id or metadata.get("user_id")
                    team_id = team_id or metadata.get("team_id")

                    items = sub.get("items", {}).get("data", [])
                    if items and not price_id:
                        price = items[0].get("price") or {}
                        price_id = stripe_id(price)

                except Exception as e:
                    logger.warning(f"Stripe fallback failed: {e}")

            # The team pays; the user who checked out may have left it or deleted their account.
            if not team_id or not price_id:
                db.commit()
                return {"status": "ignored"}

            team = team_for_subscription(db, team_id, None, None)

            if not team:
                db.commit()
                return {"status": "ignored"}

            plan = _plan_for_invoice_price(price, price_id)

            if not plan:
                logger.warning(f"Unknown price_id: {price_id}")
                db.commit()
                return {"status": "unknown_plan"}

            wallet = _locked_wallet(db, team.id)

            expiry_timestamp = invoice.get("current_period_end")

            if not expiry_timestamp:
                expiry_timestamp = (plan_line.get("period") or {}).get("end")

            expiry_date = datetime.utcfromtimestamp(expiry_timestamp) if expiry_timestamp else None

            wallet.subscription_status = "ACTIVE"
            wallet.subscription_credits = SUBSCRIPTION_GRANTS[plan]
            wallet.subscription_expires_at = expiry_date
            wallet.plan_type = plan
            # The first invoice pays for the checkout that already recorded this grant; only renewals add a row.
            if invoice.get("billing_reason") != "subscription_create":
                _record_grant(
                    db, wallet, "SUBSCRIPTION_GRANT", SUBSCRIPTION_GRANTS[plan], f"invoice_{invoice.get('id') or event_id}"
                )

            # With nobody left holding the subscription, the owner takes it so the portal still finds it.
            members = team_users(db, team)
            member_ids = {u.id for u in members}
            users = [u for u in _subscription_users(db, team, subscription_id, user_id) if u.id in member_ids]
            users = users or members[:1]
            for user in users:
                user.subscription_status = "ACTIVE"
                user.subscription_plan = plan
                user.stripe_subscription_id = subscription_id
                user.stripe_customer_id = stripe_id(invoice.get("customer")) or user.stripe_customer_id

            db.commit()
            logger.info("Subscription updated")
            return {"status": "success"}


        if event_type == "customer.subscription.updated":
            return _handle_subscription_updated(db, event)

        if event_type == "customer.subscription.deleted":
            return _handle_subscription_deleted(db, event)

        db.commit()
        return {"status": "ignored"}

    except Exception:





        logger.exception("Stripe webhook failed")
        try:
            db.rollback()
        except Exception:
            pass
        try:
            stale = (
                db.query(StripeEvent).filter(StripeEvent.id == event_id).first()
            )
            if stale:
                db.delete(stale)
                db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=500, detail="Webhook processing failed; will be retried"
        )
