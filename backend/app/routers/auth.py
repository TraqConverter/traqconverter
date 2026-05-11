from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from datetime import datetime, timedelta

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.rate_limit import rate_limit
from app.models.user import User
from app.models.team import Team
from app.models.credit import CreditWallet
from app.schemas.auth import UserRegister, UserLogin, TokenResponse
from app.core.security import hash_password, verify_password, create_access_token
from app.core.plan_features import TRIAL_DAYS, TRIAL_CREDITS
from app.routers.members import auto_accept_invites

router = APIRouter(prefix="/auth", tags=["auth"])

# Audit CRIT-7 — per-IP throttles on auth endpoints. Generous enough for
# real shared/NAT users, tight enough that a brute-force script gets
# 429'd within a second.
_login_limit = rate_limit("auth_login", max_requests=10, per_seconds=60)
_register_limit = rate_limit("auth_register", max_requests=5, per_seconds=300)


# ============================================================
# CURRENT USER
# ============================================================
@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "subscription_plan": current_user.subscription_plan,
        "subscription_status": current_user.subscription_status,
    }


# ============================================================
# UPDATE PROFILE
# ============================================================
class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None


@router.patch("/me")
def update_me(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.full_name is not None:
        name = payload.full_name.strip()
        if name and len(name) > 200:
            raise HTTPException(status_code=400, detail="Name is too long")
        current_user.full_name = name or None

    db.commit()
    db.refresh(current_user)
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
    }


# ============================================================
# CHANGE PASSWORD
# ============================================================
class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=400, detail="New password must be at least 8 characters"
        )
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=400,
            detail="New password must be different from the current one",
        )

    current_user.password_hash = hash_password(payload.new_password)
    # Audit CRIT-8: invalidate every previously-issued JWT.
    current_user.token_version = (
        int(getattr(current_user, "token_version", 0) or 0) + 1
    )
    db.commit()
    db.refresh(current_user)

    # Mint a fresh token for the device that initiated the change so the
    # user isn't immediately logged out from this page.
    new_token = create_access_token(
        {"sub": str(current_user.id)},
        token_version=int(current_user.token_version),
    )
    return {"status": "password_updated", "access_token": new_token}


# ============================================================
# DELETE ACCOUNT
# ============================================================
class DeleteAccount(BaseModel):
    password: str
    confirm: str


@router.post("/delete-account")
def delete_account(
    payload: DeleteAccount,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.confirm.strip().upper() != "DELETE":
        raise HTTPException(
            status_code=400, detail='Type "DELETE" to confirm account deletion'
        )
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect")

    team = db.query(Team).filter(Team.owner_id == current_user.id).first()
    if team:
        db.query(CreditWallet).filter(CreditWallet.team_id == team.id).delete()
        db.delete(team)

    db.delete(current_user)
    db.commit()
    return {"status": "deleted"}


# ============================================================
# REGISTER (rate limited)
# ============================================================
@router.post(
    "/register",
    response_model=TokenResponse,
    dependencies=[Depends(_register_limit)],
)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        full_name=user_data.full_name,
    )
    db.add(user)
    db.flush()

    team = Team(
        name=f"{user.full_name or user.email}'s Team",
        owner_id=user.id,
    )
    db.add(team)
    db.flush()

    # 7-day trial with 1 credit. Download is gated at the route level
    # (feature_guard's TRIAL config).
    wallet = CreditWallet(
        team_id=team.id,
        subscription_credits=TRIAL_CREDITS,
        purchased_credits=0,
        plan_type="TRIAL",
        subscription_status="TRIAL",
        subscription_expires_at=datetime.utcnow() + timedelta(days=TRIAL_DAYS),
    )
    db.add(wallet)

    user.subscription_plan = "TRIAL"
    user.subscription_status = "TRIAL"

    db.commit()
    db.refresh(user)

    try:
        auto_accept_invites(db, user)
    except Exception:
        pass

    # Embed token_version so password changes can revoke older tokens
    # (audit CRIT-8).
    token = create_access_token(
        {"sub": str(user.id)},
        token_version=int(getattr(user, "token_version", 0) or 0),
    )
    return TokenResponse(access_token=token)


# ============================================================
# LOGIN (rate limited)
# ============================================================
@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(_login_limit)],
)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    try:
        auto_accept_invites(db, user)
    except Exception:
        pass

    token = create_access_token(
        {"sub": str(user.id)},
        token_version=int(getattr(user, "token_version", 0) or 0),
    )
    return TokenResponse(access_token=token)
