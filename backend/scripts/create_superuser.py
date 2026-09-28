"""Provision (or update) a superuser.

Usage:
    python -m scripts.create_superuser

Reads SUPERUSER_EMAIL and SUPERUSER_PASSWORD from the environment.
Idempotent: re-running resets the password and re-asserts the role.
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.credit import CreditWallet
from app.models.team import Team
from app.models.user import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Never hardcode these: this repository is public.
SUPERUSER_EMAIL = os.environ.get("SUPERUSER_EMAIL", "")
SUPERUSER_PASSWORD = os.environ.get("SUPERUSER_PASSWORD", "")
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
    if not SUPERUSER_EMAIL or len(SUPERUSER_PASSWORD) < 12:
        print("Set SUPERUSER_EMAIL and SUPERUSER_PASSWORD (12+ characters) in the environment.")
        return 1
    db = SessionLocal()
    try:
        user = upsert_superuser(db)
        print(
            f"Superuser ready: id={user.id} email={user.email} "
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
