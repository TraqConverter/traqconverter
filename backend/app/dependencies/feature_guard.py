from datetime import datetime
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.credit import CreditWallet
from app.dependencies import get_current_user
from app.core.plan_features import PLAN_FEATURES


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


def effective_plan(db: Session, user: User) -> str:
    """Resolve the user's *effective* plan.

    Reads `wallet.plan_type` (canonical, set by Stripe webhook + register)
    and downgrades a TRIAL whose `subscription_expires_at` has passed to
    "EXPIRED" so feature checks fail closed.

    Returns one of: TRIAL / BASIC / PRO / EXPIRED.
    """
    team_id = _resolve_team_id(db, user)
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

    if plan in ("BASIC", "PRO"):
        if status == "ACTIVE":
            return plan
        # Subscription cancelled / inactive → treat as expired
        return "EXPIRED"

    # Legacy "STARTER" or anything else falls through as expired (no features).
    return "EXPIRED"


def require_feature(feature_name: str):
    """FastAPI dependency that 403s if the caller's plan doesn't include
    `feature_name`. Looks up the plan via the wallet so trial expirations
    fail closed.
    """
    def _dep(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        # Admin / Super Admin bypass kept from the previous implementation.
        if current_user.role in ("ADMIN", "SUPER_ADMIN"):
            return True

        plan = effective_plan(db, current_user)
        config = PLAN_FEATURES.get(plan, {})
        if not config.get(feature_name, False):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"{feature_name.replace('_', ' ').title()} isn't available "
                    f"on your current plan. Upgrade to Pro to unlock it."
                ),
            )
        return True

    return _dep
