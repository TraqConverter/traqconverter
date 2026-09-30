import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import stripe

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.credit import CreditWallet
from app.models.stripe_event import StripeEvent
from app.config import settings
from app.core.plan_features import CREDIT_PACKS as PLAN_CREDIT_PACKS
from app.core.plan_features import PAID_PLANS, SALES_EMAIL, SUBSCRIPTION_GRANTS

logger = logging.getLogger(__name__)


def _resolve_user_team(db: Session, user: User):
    """Audit P1 #6: owner-or-member so invited members can buy
    credits and upgrade plans.
    """
    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if team:
        return team
    membership = (
        db.query(TeamMember).filter(TeamMember.user_id == user.id).first()
    )
    if membership:
        return (
            db.query(Team).filter(Team.id == membership.team_id).first()
        )
    return None


router = APIRouter(prefix="/subscription", tags=["subscription"])

stripe.api_key = settings.stripe_secret_key


stripe.max_network_retries = 3





def plan_price_id(plan: str):
    """The Stripe price for a paid plan, from STRIPE_PRICE_<PLAN>; None when unset."""
    return getattr(settings, f"STRIPE_PRICE_{plan}", None) or None


PLAN_PRICE_MAP = {plan: plan_price_id(plan) for plan in PAID_PLANS}





@router.post("/create-checkout-session")
def create_checkout_session(
    plan: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
     FIXED:
    - No hardcoded price IDs
    - Plan-based mapping
    - Environment configurable
    """


    if plan.upper() not in PLAN_PRICE_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan")
    price_id = PLAN_PRICE_MAP[plan.upper()]
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"This plan isn't available yet. Contact us at {SALES_EMAIL} to sign up.",
        )


    team = _resolve_user_team(db, current_user)
    if not team:
        raise HTTPException(status_code=400, detail="Team not found")




    base_success = settings.STRIPE_SUCCESS_URL
    join = "&" if "?" in base_success else "?"
    success_url = f"{base_success}{join}session_id={{CHECKOUT_SESSION_ID}}"

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="subscription",
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=settings.STRIPE_CANCEL_URL,


        metadata={
            "user_id": str(current_user.id),
            "team_id": str(team.id),
            "plan": plan.upper(),
        },


        subscription_data={
            "metadata": {
                "user_id": str(current_user.id),
                "team_id": str(team.id),
                "plan": plan.upper(),
            }
        }
    )

    return {"checkout_url": session.url}









@router.post("/sync-session")
def sync_session(
    session_id: str = Query(..., description="Stripe Checkout Session id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"sync-session called with id={session_id[:14]}…")
    if not session_id or not session_id.startswith("cs_"):
        raise HTTPException(status_code=400, detail="Invalid session id")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        logger.warning(f"sync-session retrieve failed: {e}")
        raise HTTPException(status_code=404, detail="Stripe session not found")


    metadata = session.get("metadata") or {}
    if metadata.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your checkout session")

    payment_status = session.get("payment_status")
    if payment_status not in ("paid", "no_payment_required"):

        return {"status": "pending", "payment_status": payment_status}

    plan = (metadata.get("plan") or "").upper()
    team_id = metadata.get("team_id")
    purchase_type = (metadata.get("type") or "").lower()
    mode = session.get("mode")

    if not team_id:
        return {"status": "ignored"}

    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")




    if purchase_type == "credit_purchase" or mode == "payment":
        try:
            credits = int(metadata.get("credits", 0))
        except (TypeError, ValueError):
            credits = 0
        if credits <= 0:
            return {"status": "ignored"}

        reference = f"checkout_{session.get('id')}"
        existing = (
            db.query(StripeEvent).filter(StripeEvent.id == reference).first()
        )
        if existing:
            wallet = (
                db.query(CreditWallet)
                .filter(CreditWallet.team_id == team_id)
                .first()
            )
            return {
                "status": "already_processed",
                "kind": "credits",
                "credits_added": credits,
                "purchased_credits": (
                    wallet.purchased_credits if wallet else credits
                ),
            }

        wallet = (
            db.query(CreditWallet)
            .filter(CreditWallet.team_id == team.id)
            .with_for_update()
            .first()
        )
        if not wallet:
            wallet = CreditWallet(
                team_id=team.id,
                purchased_credits=0,
                subscription_credits=0,
                subscription_status="INACTIVE",
            )
            db.add(wallet)
            db.flush()

        wallet.purchased_credits += credits
        db.add(StripeEvent(id=reference, event_type="credit_grant"))
        db.commit()

        logger.info(
            f"sync-session credited +{credits} to team {team.id} "
            f"(new purchased={wallet.purchased_credits})"
        )
        return {
            "status": "success",
            "kind": "credits",
            "credits_added": credits,
            "purchased_credits": wallet.purchased_credits,
        }




    if mode != "subscription" or plan not in SUBSCRIPTION_GRANTS:
        return {"status": "ignored"}

    reference = f"sub_checkout_{session.get('id')}"
    existing = db.query(StripeEvent).filter(StripeEvent.id == reference).first()
    if existing:
        wallet = (
            db.query(CreditWallet)
            .filter(CreditWallet.team_id == team_id)
            .first()
        )
        return {
            "status": "already_processed",
            "tier": (wallet.plan_type if wallet else plan),
        }

    wallet = (
        db.query(CreditWallet)
        .filter(CreditWallet.team_id == team.id)
        .with_for_update()
        .first()
    )
    if not wallet:
        wallet = CreditWallet(
            team_id=team.id,
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

    user = db.query(User).filter(User.id == current_user.id).first()
    if user:
        user.subscription_status = "ACTIVE"
        user.subscription_plan = plan
        user.stripe_subscription_id = session.get("subscription")

    db.add(StripeEvent(id=reference, event_type="subscription_grant"))
    db.commit()

    logger.info(f"sync-session activated {plan} for team {team.id}")
    return {"status": "success", "tier": plan}







CREDIT_PACKS = {
    pack["credits"]: getattr(settings, f"STRIPE_PRICE_CREDITS_{pack['credits']}", None)
    for pack in PLAN_CREDIT_PACKS
}





@router.post("/purchase-credits")
def purchase_credits(
    amount: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a Stripe Checkout Session for a fixed credit pack.

    `amount` must match one of the configured pack sizes (10, 25, 50).
    Each pack maps to a Stripe price ID supplied via .env so pricing
    is owned by the Stripe dashboard rather than the server. The
    Stripe webhook + /sync-session credit the wallet when payment
    succeeds — same flow as the subscription upgrade path.
    """

    if amount not in CREDIT_PACKS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid credit pack. Available packs: "
                f"{sorted(CREDIT_PACKS.keys())}"
            ),
        )

    price_id = CREDIT_PACKS[amount]
    if not price_id:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Credit pack of {amount} isn't fully configured "
                "(missing STRIPE_PRICE_CREDITS_* env var)."
            ),
        )

    team = _resolve_user_team(db, current_user)
    if not team:
        raise HTTPException(status_code=400, detail="Team not found")




    base_success = settings.STRIPE_SUCCESS_URL
    join = "&" if "?" in base_success else "?"
    success_url = f"{base_success}{join}session_id={{CHECKOUT_SESSION_ID}}"

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="payment",
        line_items=[
            {"price": price_id, "quantity": 1},
        ],
        success_url=success_url,
        cancel_url=settings.STRIPE_CANCEL_URL,
        metadata={
            "type": "credit_purchase",
            "user_id": str(current_user.id),
            "team_id": str(team.id),
            "credits": str(amount),
        },
    )

    return {"checkout_url": session.url}
