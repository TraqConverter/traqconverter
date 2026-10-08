"""Team-level lookups of the Stripe customer and subscription stored on the team's users."""
import logging
import uuid

import stripe
from sqlalchemy.orm import Session

from app.core.plan_features import PAID_PLANS
from app.models.credit import CreditWallet
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.user import User

logger = logging.getLogger(__name__)


def stripe_id(value):
    """The id of an expandable Stripe field, whether Stripe sent a string or an object."""
    if isinstance(value, dict):
        return value.get("id")
    return value or None


def team_users(db: Session, team: Team) -> list:
    """The owner first, then the members."""
    owner = db.query(User).filter(User.id == team.owner_id).first()
    members = (
        db.query(User)
        .join(TeamMember, TeamMember.user_id == User.id)
        .filter(TeamMember.team_id == team.id, User.id != team.owner_id)
        .all()
    )
    return [u for u in [owner, *members] if u]


def team_of_user(db: Session, user: User):
    from app.dependencies.tenant import active_team

    return active_team(db, user)


def team_for_subscription(db: Session, team_id, customer_id, subscription_id):
    """The team a Stripe subscription belongs to: its metadata first, then the ids stored on users."""
    try:
        team_uuid = uuid.UUID(str(team_id)) if team_id else None
    except ValueError:
        team_uuid = None
    if team_uuid:
        team = db.query(Team).filter(Team.id == team_uuid).first()
        if team:
            return team
    for column, value in (
        (User.stripe_subscription_id, subscription_id),
        (User.stripe_customer_id, customer_id),
    ):
        if not value:
            continue
        user = db.query(User).filter(column == value).first()
        if user:
            team = team_of_user(db, user)
            if team:
                return team
    return None


def team_subscription_ids(db: Session, team: Team) -> set:
    return {u.stripe_subscription_id for u in team_users(db, team) if u.stripe_subscription_id}


def is_current_subscription(db: Session, team: Team, subscription_id) -> bool:
    """False for a subscription other than the one the team is known to pay through."""
    known = team_subscription_ids(db, team)
    return not known or subscription_id in known


def has_active_subscription(db: Session, team: Team) -> bool:
    """A paid plan that is ACTIVE and billed through a Stripe subscription (not granted by hand)."""
    wallet = db.query(CreditWallet).filter(CreditWallet.team_id == team.id).first()
    if not wallet:
        return False
    if (wallet.plan_type or "").upper() not in PAID_PLANS:
        return False
    if (wallet.subscription_status or "").upper() != "ACTIVE":
        return False
    return bool(team_subscription_ids(db, team))


def team_customer_id(db: Session, team: Team):
    """The team's Stripe customer, recovering it from a stored subscription when only that was saved."""
    users = team_users(db, team)
    for user in users:
        if user.stripe_customer_id:
            return user.stripe_customer_id
    for user in users:
        if not user.stripe_subscription_id:
            continue
        try:
            sub = stripe.Subscription.retrieve(user.stripe_subscription_id)
        except Exception as e:
            logger.warning(f"Could not read subscription for team {team.id}: {e}")
            continue
        customer = stripe_id(sub.get("customer"))
        if customer:
            user.stripe_customer_id = customer
            db.commit()
            return customer
    return None
