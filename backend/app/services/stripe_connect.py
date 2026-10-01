"""Stripe Connect: each team's own Stripe account, and protected-link payments charged directly on it."""
from __future__ import annotations

import logging
from typing import Optional

import stripe
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key

# Full Dashboard accounts sign in to Stripe themselves; login links only exist for Express accounts.
DASHBOARD_URL = "https://dashboard.stripe.com/"

# The translator owns the account: full Stripe Dashboard, pays Stripe's fees, and Stripe (not us) covers losses.
CONTROLLER = {
    "stripe_dashboard": {"type": "full"},
    "fees": {"payer": "account"},
    "losses": {"payments": "stripe"},
}


def status_of(account) -> str:
    if account.get("charges_enabled"):
        return "active"
    return "restricted" if account.get("details_submitted") else "pending"


def requirements_due(account) -> int:
    req = account.get("requirements") or {}
    return len(set(req.get("currently_due") or []) | set(req.get("past_due") or []))


def summary(team, account=None) -> dict:
    """Payment-settings fields; with no fresh account object, what's stored."""
    if not team.stripe_account_id:
        return {
            "stripe_status": None,
            "stripe_charges_enabled": False,
            "stripe_details_submitted": False,
            "stripe_requirements_due": 0,
        }
    status = team.stripe_account_status or "pending"
    if account is None:
        return {
            "stripe_status": status,
            "stripe_charges_enabled": status == "active",
            "stripe_details_submitted": status != "pending",
            "stripe_requirements_due": 0,
        }
    return {
        "stripe_status": status,
        "stripe_charges_enabled": bool(account.get("charges_enabled")),
        "stripe_details_submitted": bool(account.get("details_submitted")),
        "stripe_requirements_due": requirements_due(account),
    }


def is_active(team) -> bool:
    return bool(team and team.stripe_account_id and team.stripe_account_status == "active")


def ensure_account(db: Session, team, user, country: Optional[str] = None) -> str:
    """The team's connected account id, creating the account the first time."""
    if team.stripe_account_id:
        return team.stripe_account_id
    account = stripe.Account.create(
        country=(country or settings.STRIPE_CONNECT_DEFAULT_COUNTRY).upper(),
        email=user.email,
        controller=CONTROLLER,
        capabilities={"card_payments": {"requested": True}},
        business_profile={"product_description": "Translation services"},
        metadata={"team_id": str(team.id)},
        # A double click must not open two accounts.
        idempotency_key=f"connect-account-{team.id}",
    )
    team.stripe_account_id = account["id"]
    team.stripe_account_status = status_of(account)
    db.commit()
    return team.stripe_account_id


def onboarding_url(account_id: str) -> str:
    back = f"{settings.FRONTEND_URL.rstrip('/')}/settings/account?stripe=return#payments"
    link = stripe.AccountLink.create(
        account=account_id,
        type="account_onboarding",
        refresh_url=back,
        return_url=back,
    )
    return link["url"]


def refresh(db: Session, team):
    """Fetch the account from Stripe and store its status. Returns the account, or None if Stripe can't be reached."""
    try:
        account = stripe.Account.retrieve(team.stripe_account_id)
    except Exception:
        logger.exception("Couldn't refresh Stripe account %s", team.stripe_account_id)
        return None
    apply(db, team, account)
    return account


def apply(db: Session, team, account) -> None:
    status = status_of(account)
    if team.stripe_account_status != status:
        team.stripe_account_status = status
        db.commit()


def fee_cents(amount_cents: int) -> int:
    return round(amount_cents * float(settings.PLATFORM_FEE_PERCENT or 0) / 100)


def checkout_url(link, team, token: str) -> str:
    """A Checkout Session on the team's own account (a direct charge). Payment methods are whatever that account enabled."""
    page = f"{settings.FRONTEND_URL.rstrip('/')}/d/{token}"
    metadata = {"link_id": str(link.id), "project_id": str(link.project_id), "team_id": str(team.id)}
    intent = {"description": f"Translation: {link.file_name}", "metadata": metadata}
    fee = fee_cents(link.amount_cents)
    if fee > 0:
        intent["application_fee_amount"] = fee
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "quantity": 1,
            "price_data": {
                "currency": (link.currency or "EUR").lower(),
                "unit_amount": link.amount_cents,
                "product_data": {"name": f"Translation: {link.file_name}"},
            },
        }],
        payment_intent_data=intent,
        metadata=metadata,
        client_reference_id=str(link.id),
        success_url=f"{page}?paid=1",
        cancel_url=page,
        stripe_account=team.stripe_account_id,
    )
    return session["url"]
