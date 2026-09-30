import logging
from datetime import datetime
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.credit import CreditWallet
from app.dependencies import get_current_user
from app.core.plan_features import PAID_PLANS, PLAN_FEATURES

logger = logging.getLogger(__name__)

ADMIN_ROLES = ("SUPERUSER", "SUPER_ADMIN", "ADMIN")


def _is_admin(user) -> bool:
    return (getattr(user, "role", None) or "").upper() in ADMIN_ROLES


def _resolve_team_id(db: Session, user: User):
    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if team:
        return team.id
    membership = (
        db.query(TeamMember).filter(TeamMember.user_id == user.id).first()
    )
    if membership:
        return membership.team_id
    return None


def _wallet_plan(db: Session, team_id) -> str:
    """The plan the team's wallet grants: TRIAL, a paid plan, or EXPIRED."""
    if team_id is None:
        return "EXPIRED"

    wallet = (
        db.query(CreditWallet).filter(CreditWallet.team_id == team_id).first()
    )
    if not wallet:
        return "EXPIRED"

    plan = (wallet.plan_type or "TRIAL").upper()
    status = (wallet.subscription_status or "").upper()

    if plan == "TRIAL":
        if (
            wallet.subscription_expires_at
            and wallet.subscription_expires_at < datetime.utcnow()
        ):
            return "EXPIRED"
        return "TRIAL"

    if plan in PAID_PLANS and status == "ACTIVE":
        return plan

    return "EXPIRED"


def effective_plan(db: Session, user: User) -> str:
    """Resolve the user's *effective* plan.

    Reads `wallet.plan_type` (canonical, set by Stripe webhook + register)
    and downgrades a TRIAL whose `subscription_expires_at` has passed to
    "EXPIRED" so feature checks fail closed.

    Returns one of: TRIAL / BASIC / PRO / STUDIO / AGENCY / EXPIRED.

    Special-case: users with role SUPERUSER / SUPER_ADMIN / ADMIN are
    always treated as PRO regardless of their wallet state, so the
    operator account never runs out of credits or features.
    """

    if _is_admin(user):
        return "PRO"

    return _wallet_plan(db, _resolve_team_id(db, user))


def team_plan(db: Session, team_id) -> str:
    """The team's plan for work with no request user; a team owned by an admin is PRO."""
    if team_id is None:
        return "EXPIRED"
    owner = (
        db.query(User.role)
        .join(Team, Team.owner_id == User.id)
        .filter(Team.id == team_id)
        .first()
    )
    if owner and (owner.role or "").upper() in ADMIN_ROLES:
        return "PRO"
    return _wallet_plan(db, team_id)


def plan_allows(plan: str, feature_name: str) -> bool:
    return bool(PLAN_FEATURES.get(plan, {}).get(feature_name, False))


def _safe_team_plan(db: Session, team_id) -> str:
    # A failed lookup denies the features but leaves the caller's transaction usable.
    try:
        with db.begin_nested():
            return team_plan(db, team_id)
    except Exception:
        logger.exception("Plan lookup failed (team=%s); treating as no plan", team_id)
        return "EXPIRED"


def team_has_feature(db: Session, team_id, feature_name: str) -> bool:
    """For background work: whether the team's plan includes `feature_name`. Never raises; fails closed."""
    return plan_allows(_safe_team_plan(db, team_id), feature_name)


def project_has_feature(db: Session, project, feature_name: str) -> bool:
    """team_has_feature for a project's team, resolved once per project object (one job or request)."""
    if db is None or project is None:
        return False
    plan = getattr(project, "_team_plan", None)
    if not isinstance(plan, str):
        plan = _safe_team_plan(db, getattr(project, "team_id", None))
        try:
            project._team_plan = plan
        except Exception:
            pass
    return plan_allows(plan, feature_name)


def user_has_feature(db: Session, user: User, feature_name: str) -> bool:
    return _is_admin(user) or plan_allows(effective_plan(db, user), feature_name)


def require_any_feature(*feature_names: str):
    """403 unless the caller's plan includes at least one of `feature_names`."""
    def _dep(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        if _is_admin(current_user):
            return True
        plan = effective_plan(db, current_user)
        if not any(plan_allows(plan, f) for f in feature_names):
            raise HTTPException(
                status_code=403,
                detail="This isn't available on your current plan. Upgrade to unlock it.",
            )
        return True

    return _dep


def require_feature(feature_name: str):
    """FastAPI dependency that 403s if the caller's plan doesn't include
    `feature_name`. Looks up the plan via the wallet so trial expirations
    fail closed.
    """
    def _dep(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):

        if current_user.role in ("ADMIN", "SUPER_ADMIN"):
            return True

        if not plan_allows(effective_plan(db, current_user), feature_name):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"{feature_name.replace('_', ' ').title()} isn't available "
                    f"on your current plan. Upgrade to Pro to unlock it."
                ),
            )
        return True

    return _dep
