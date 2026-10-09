"""Stripe Connect: each team's own Stripe account, and protected-link payments charged directly on it."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

import requests
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

STRIPE_API = "https://api.stripe.com"
V2_TIMEOUT = (5, 20)

# Error codes from /v2/core/accounts that mean the platform's own Connect setup isn't done.
PLATFORM_NOT_READY = {
    "connect_profile_not_submitted",
    "connect_identity_not_verified",
    "platform_registration_required",
    "account_create_activation_required",
}
COUNTRY_NOT_SUPPORTED = {"cross_border_connected_account_creation_not_allowed"}


class StripeV2Error(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def _uses_v2() -> bool:
    return settings.STRIPE_CONNECT_ACCOUNTS_API == "v2"


def _v2_request(method: str, path: str, json=None, params=None, idempotency_key: Optional[str] = None) -> dict:
    """One call to Stripe's v2 API; stripe-python 10.x has no v2 support."""
    headers = {
        "Authorization": f"Bearer {settings.stripe_secret_key}",
        "Stripe-Version": settings.STRIPE_V2_API_VERSION,
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        resp = requests.request(method, f"{STRIPE_API}{path}", headers=headers, json=json, params=params,
                                timeout=V2_TIMEOUT)
    except requests.RequestException as exc:
        raise StripeV2Error("api_connection_error", str(exc), 0) from exc
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        err = err if isinstance(err, dict) else {}
        raise StripeV2Error(err.get("code") or f"http_{resp.status_code}", err.get("message") or resp.text[:200],
                            resp.status_code)
    return body


TOS_REQUIREMENT = "identity.attestations.terms_of_service"


def _v2_entries(account: dict) -> list:
    return (account.get("requirements") or {}).get("entries") or []


def _v2_due(account: dict) -> dict:
    """v2 requirement entries bucketed like v1's requirements.currently_due / past_due."""
    due = {"currently_due": [], "past_due": []}
    for entry in _v2_entries(account):
        # Details Stripe is still verifying stay past_due, but there's nothing for the translator to do.
        if entry.get("awaiting_action_from") == "stripe":
            continue
        status = (entry.get("minimum_deadline") or {}).get("status")
        if status in due:
            due[status].append(entry.get("description") or "")
    return due


def from_v2(account: dict) -> dict:
    """A v2.core.account in the v1 shape the rest of this module reads, plus its status."""
    merchant = (account.get("configuration") or {}).get("merchant") or {}
    capability = ((merchant.get("capabilities") or {}).get("card_payments") or {}).get("status")
    due = _v2_due(account)
    # Hosted onboarding ends with accepting Stripe's terms; until then the form was never submitted.
    onboarded = not any((e.get("description") or "").startswith(TOS_REQUIREMENT) for e in _v2_entries(account))
    if capability == "active":
        status = "active"
    elif not onboarded:
        status = "pending"
    else:
        status = "restricted"
    return {
        "id": account.get("id"),
        "charges_enabled": capability == "active",
        "details_submitted": onboarded and not (due["currently_due"] or due["past_due"]),
        "requirements": due,
        "status": status,
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
    # A double click must not open two accounts: hold the team row while creating, then re-check.
    from app.models.team import Team

    locked = db.query(Team).filter(Team.id == team.id).with_for_update().one()
    if locked.stripe_account_id:
        return locked.stripe_account_id
    country = country or settings.STRIPE_CONNECT_DEFAULT_COUNTRY
    # Unique per attempt: Stripe replays a reused key's first answer for 24h, errors included.
    key = f"connect-account-{team.id}-{uuid.uuid4().hex}"
    if _uses_v2():
        account = from_v2(_v2_request("POST", "/v2/core/accounts", json={
            "contact_email": user.email,
            "display_name": locked.name or user.email,
            "identity": {"country": country.lower()},
            "dashboard": "full",
            "defaults": {"responsibilities": {"fees_collector": "stripe", "losses_collector": "stripe"}},
            "configuration": {"merchant": {"capabilities": {"card_payments": {"requested": True}}}},
            "include": ["configuration.merchant", "requirements", "identity", "defaults"],
            "metadata": {"team_id": str(team.id)},
        }, idempotency_key=key))
        status = account["status"]
    else:
        account = stripe.Account.create(
            country=country.upper(),
            email=user.email,
            controller=CONTROLLER,
            capabilities={"card_payments": {"requested": True}, "transfers": {"requested": True}},
            business_profile={"product_description": "Translation services"},
            metadata={"team_id": str(team.id)},
            idempotency_key=key,
        )
        status = status_of(account)
    locked.stripe_account_id = account["id"]
    locked.stripe_account_status = status
    db.commit()
    return locked.stripe_account_id


def onboarding_url(account_id: str) -> str:
    back = f"{settings.FRONTEND_URL.rstrip('/')}/settings/account?stripe=return#payments"
    if _uses_v2():
        link = _v2_request("POST", "/v2/core/account_links", json={
            "account": account_id,
            "use_case": {
                "type": "account_onboarding",
                # No "configurations" here: API version 2026-09-30.endive rejects it as an unknown field.
                "account_onboarding": {"return_url": back, "refresh_url": back},
            },
        })
        return link["url"]
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
        if _uses_v2():
            account = from_v2(_v2_request(
                "GET", f"/v2/core/accounts/{team.stripe_account_id}",
                params=[("include[0]", "configuration.merchant"), ("include[1]", "requirements")],
            ))
            status = account["status"]
        else:
            account = stripe.Account.retrieve(team.stripe_account_id)
            status = status_of(account)
    except Exception:
        logger.exception("Couldn't refresh Stripe account %s", team.stripe_account_id)
        return None
    _store(db, team, status)
    return account


def apply(db: Session, team, account) -> None:
    """From a v1 account.updated event."""
    _store(db, team, status_of(account))


def _store(db: Session, team, status: str) -> None:
    if team.stripe_account_status != status:
        team.stripe_account_status = status
        db.commit()


def fee_cents(amount_cents: int) -> int:
    return round(amount_cents * float(settings.PLATFORM_FEE_PERCENT or 0) / 100)


CHECKOUT_MINUTES = 30  # Stripe's shortest session lifetime


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
        expires_at=int(time.time()) + CHECKOUT_MINUTES * 60,
        success_url=f"{page}?paid=1",
        cancel_url=page,
        stripe_account=team.stripe_account_id,
    )
    return session["url"]
