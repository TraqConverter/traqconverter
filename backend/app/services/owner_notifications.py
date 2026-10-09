"""Emails to our business inbox about our own subscribers. Never about their clients."""
import logging
import uuid
from datetime import datetime

from app.config import settings
from app.core.plan_features import CREDIT_PACKS, PLANS
from app.core.roles import is_staff
from app.models.team import Team
from app.models.user import User
from app.services import email_service

logger = logging.getLogger(__name__)

_PLAN_BY_CODE = {p["code"]: p for p in PLANS}
_SYMBOLS = {"eur": "€", "gbp": "£", "usd": "$"}


def recipient():
    return (settings.OWNER_NOTIFY_EMAIL or "").strip() or None


def notify(background_tasks, kind: str, build, *args) -> None:
    """Queue the email `build(*args)` describes, sent after the response; never raises."""
    if not recipient():
        return
    try:
        message = build(*args)
        if message:
            background_tasks.add_task(send, kind, *message)
    except Exception as e:
        logger.warning("Owner notice (%s) not prepared: %s", kind, type(e).__name__)


def send(kind: str, subject: str, rows: list) -> None:
    to = recipient()
    if not to:
        return
    try:
        html, text = email_service.render_owner_notice_email(subject=subject, rows=rows)
        if not email_service.send_email(to=to, subject=subject, html=html, text_fallback=text):
            logger.warning("Owner notice (%s) not sent", kind)
    except Exception as e:
        logger.warning("Owner notice (%s) failed: %s", kind, type(e).__name__)


def _money(cents, currency) -> str:
    if cents is None:
        return "unknown"
    code = (currency or "eur").lower()
    symbol = _SYMBOLS.get(code)
    amount = f"{cents / 100:.2f}"
    return f"{symbol}{amount}" if symbol else f"{amount} {code.upper()}"


def _plan_name(plan) -> str:
    p = _PLAN_BY_CODE.get((plan or "").upper())
    return p["name"] if p else (plan or "unknown").capitalize()


def _plan_price(plan) -> str:
    p = _PLAN_BY_CODE.get((plan or "").upper())
    return f"€{p['price_eur']}/month" if p else ""


def _plan_label(plan) -> str:
    return f"{_plan_name(plan)} {_plan_price(plan)}".strip()


def _day(d: datetime) -> str:
    return f"{d.day} {d:%b}"


def _full_date(d: datetime) -> str:
    return f"{d.day} {d:%b %Y}"


def _utc_time(d: datetime) -> str:
    return f"{d.day} {d:%b %Y, %H:%M} UTC"


def _team(db, team_or_id):
    if isinstance(team_or_id, Team):
        return team_or_id
    try:
        team_id = uuid.UUID(str(team_or_id))
    except (TypeError, ValueError):
        return None
    return db.query(Team).filter(Team.id == team_id).first()


def _team_and_owner(db, team_or_id):
    """The team and its owner, or None for a team we can't find or that belongs to platform staff."""
    team = _team(db, team_or_id) if team_or_id else None
    if team is None:
        return None
    owner = db.query(User).filter(User.id == team.owner_id).first()
    if owner is None or is_staff(owner):
        return None
    return team, owner


def signup(db, user, team_id, invited: bool):
    if is_staff(user):
        return None
    at = user.terms_accepted_at or datetime.utcnow()
    name = user.full_name or user.email
    team = _team(db, team_id)
    team_name = team.name if team else "unknown team"
    if invited:
        subject = f"New sign-up: {name} (joined {team_name})"
        how = f"Joined {team_name} by invite"
    else:
        subject = f"New sign-up: {name} (trial)"
        how = "Started a free trial"
    rows = [
        ("Name", user.full_name or "(not given)"),
        ("Email", user.email),
        ("Team", team_name),
        ("How", how),
        ("Signed up", _utc_time(at)),
    ]
    return subject, rows


def new_subscription(db, team_id, plan, amount_cents, currency):
    found = _team_and_owner(db, team_id)
    if not found:
        return None
    team, owner = found
    subject = f"New subscription: {team.name} — {_plan_label(plan)}"
    rows = [
        ("Team", team.name),
        ("Owner", owner.email),
        ("Plan", _plan_name(plan)),
        ("Price", _plan_price(plan)),
        ("Paid at checkout", _money(amount_cents, currency)),
    ]
    return subject, rows


def plan_change(db, team, old_plan, new_plan):
    found = _team_and_owner(db, team)
    if not found:
        return None
    team, owner = found
    old_p, new_p = _PLAN_BY_CODE.get(old_plan), _PLAN_BY_CODE.get(new_plan)
    direction = "upgrade" if old_p and new_p and new_p["price_eur"] > old_p["price_eur"] else "downgrade"
    subject = f"Plan change: {team.name} — {_plan_name(old_plan)} to {_plan_name(new_plan)} ({direction})"
    rows = [
        ("Team", team.name),
        ("Owner", owner.email),
        ("From", _plan_label(old_plan)),
        ("To", _plan_label(new_plan)),
    ]
    return subject, rows


def credit_pack(db, team_id, credits, amount_cents, currency):
    found = _team_and_owner(db, team_id)
    if not found:
        return None
    team, owner = found
    pack = next((p for p in CREDIT_PACKS if p["credits"] == credits), None)
    amount = _money(amount_cents, currency)
    subject = f"Credit pack: {team.name} — {credits} credits {amount}"
    rows = [
        ("Team", team.name),
        ("Owner", owner.email),
        ("Pack", pack["name"] if pack else "Custom"),
        ("Credits", str(credits)),
        ("Amount", amount),
    ]
    return subject, rows


def cancellation_scheduled(db, team, plan, ends_at):
    found = _team_and_owner(db, team)
    if not found:
        return None
    team, owner = found
    ends = f", ends {_day(ends_at)}" if ends_at else ""
    subject = f"Cancellation: {team.name} — {_plan_name(plan)}{ends}"
    rows = [
        ("Team", team.name),
        ("Owner", owner.email),
        ("Plan", _plan_label(plan)),
        ("Status", "Cancelled; the plan stays active until the end date"),
        ("Ends", _full_date(ends_at) if ends_at else "unknown"),
    ]
    return subject, rows


def subscription_ended(db, team, plan, ended_at):
    found = _team_and_owner(db, team)
    if not found:
        return None
    team, owner = found
    subject = f"Subscription ended: {team.name} — {_plan_name(plan)}, ended {_day(ended_at)}"
    rows = [
        ("Team", team.name),
        ("Owner", owner.email),
        ("Plan", _plan_label(plan)),
        ("Ended", _full_date(ended_at)),
    ]
    return subject, rows
