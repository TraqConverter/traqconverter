"""Provision (or update) a superuser.

Usage:
    python -m scripts.create_superuser

Idempotent — running it twice resets the password and re-asserts the
SUPERUSER role / Pro plan. Safe to run on every deploy.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

# Make `app...` imports work when run via `python -m scripts.create_superuser`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.credit import CreditWallet
from app.models.team import Team
from app.models.user import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPERUSER_EMAIL = "info@espressotranslations.com"
SUPERUSER_PASSWORD = "Translation2026!"
SUPERUSER_NAME = "Espresso Translations Admin"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def upsert_superuser(db: Session) -> User:
    user = db.query(User).filter(User.email == SUPERUSER_EMAIL).first()
    pw_hash = pwd_context.hash(SUPERUSER_PASSWORD)

    if user:
        user.password_hash = pw_hash
        user.full_name = SUPERUSER_NAME
        user.role = "SUPERUSER"
        user.is_active = True
        user.subscription_status = "ACTIVE"
        user.subscription_plan = "PRO"
        # Bump token_version to invalidate any leaked old JWTs.
        user.token_version = (user.token_version or 0) + 1
        logger.info("Superuser exists — refreshed password + role")
    else:
        user = User(
            email=SUPERUSER_EMAIL,
            password_hash=pw_hash,
            full_name=SUPERUSER_NAME,
            role="SUPERUSER",
            is_active=True,
            subscription_status="ACTIVE",
            subscription_plan="PRO",
            token_version=0,
        )
        db.add(user)
        db.flush()
        logger.info("Created new superuser %s", SUPERUSER_EMAIL)

    # Ensure they have a team + wallet so feature gates that read wallet
    # state don't complain. The feature_guard short-circuits the
    # SUPERUSER role to PRO so wallet contents don't actually matter,
    # but having them around keeps the rest of the app's assumptions
    # intact.
    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if not team:
        team = Team(owner_id=user.id, name="Espresso Translations")
        db.add(team)
        db.flush()

    wallet = (
        db.query(CreditWallet).filter(CreditWallet.team_id == team.id).first()
    )
    if not wallet:
        wallet = CreditWallet(
            team_id=team.id,
            purchased_credits=0,
            subscription_credits=999999,
            subscription_status="ACTIVE",
            plan_type="PRO",
            subscription_expires_at=None,
        )
        db.add(wallet)
    else:
        wallet.subscription_status = "ACTIVE"
        wallet.plan_type = "PRO"
        wallet.subscription_credits = max(
            wallet.subscription_credits or 0, 999999
        )
        wallet.subscription_expires_at = None

    db.commit()
    return user


def main() -> int:
    db = SessionLocal()
    try:
        user = upsert_superuser(db)
        print(
            f"✅ Superuser ready: id={user.id} email={user.email} "
            f"role={user.role}"
        )
        return 0
    except Exception:
        db.rollback()
        logger.exception("Failed to create superuser")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
