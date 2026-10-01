"""Webhook for events on teams' own Stripe accounts (Connect): paid protected links, account status changes."""
import logging
import uuid

import stripe
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.delivery_link import DeliveryLink
from app.models.project import TranslationProject
from app.models.stripe_event import StripeEvent
from app.models.team import Team
from app.services import delivery_links, stripe_connect
from app.services.stripe_billing import stripe_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe/connect", tags=["Stripe"])

_PAID_EVENTS = ("checkout.session.completed", "checkout.session.async_payment_succeeded")


def _link_paid(db: Session, event, background_tasks: BackgroundTasks) -> str:
    session = event["data"]["object"]
    if session.get("payment_status") != "paid":
        return "ignored"
    try:
        link_id = uuid.UUID(str((session.get("metadata") or {}).get("link_id")))
    except ValueError:
        return "ignored"
    row = (
        db.query(DeliveryLink, Team)
        .join(TranslationProject, TranslationProject.id == DeliveryLink.project_id)
        .join(Team, Team.id == TranslationProject.team_id)
        .filter(DeliveryLink.id == link_id)
        .first()
    )
    # Only the account the link's team connected can pay for it.
    if row is None or not row.Team.stripe_account_id or row.Team.stripe_account_id != event.get("account"):
        logger.warning("Connect payment for link %s from account %s doesn't match", link_id, event.get("account"))
        return "ignored"
    link = row.DeliveryLink
    if not link.protected:
        return "ignored"
    if delivery_links.mark_paid(db, link, stripe_id(session.get("payment_intent"))):
        from app.routers.delivery_links import notify_stripe_paid

        background_tasks.add_task(notify_stripe_paid, link.id)
    return "unlocked"


def _account_updated(db: Session, event) -> str:
    account = event["data"]["object"]
    team = db.query(Team).filter(Team.stripe_account_id == account.get("id")).first()
    if team is None:
        return "ignored"
    stripe_connect.apply(db, team, account)
    return "updated"


def _deauthorized(db: Session, event) -> str:
    team = db.query(Team).filter(Team.stripe_account_id == event.get("account")).first()
    if team is None:
        return "ignored"
    team.stripe_account_id = None
    team.stripe_account_status = None
    return "disconnected"


@router.post("/webhook")
async def stripe_connect_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    secret = settings.STRIPE_CONNECT_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="Connect webhook not configured")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, request.headers.get("stripe-signature"), secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    event_id, event_type = event["id"], event["type"]
    try:
        db.add(StripeEvent(id=event_id, event_type=event_type))
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"status": "already_processed"}

    try:
        if event_type in _PAID_EVENTS:
            result = _link_paid(db, event, background_tasks)
        elif event_type == "account.updated":
            result = _account_updated(db, event)
        elif event_type == "account.application.deauthorized":
            result = _deauthorized(db, event)
        else:
            result = "ignored"
        db.commit()
        return {"status": result}
    except Exception:
        logger.exception("Stripe Connect webhook failed (%s)", event_id)
        db.rollback()
        try:
            db.query(StripeEvent).filter(StripeEvent.id == event_id).delete()
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=500, detail="Webhook processing failed; will be retried")
