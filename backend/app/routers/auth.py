from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from datetime import datetime, timedelta

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.team import Team
from app.models.credit import CreditWallet
from app.schemas.auth import UserRegister, UserLogin, TokenResponse
from app.core.security import hash_password, verify_password, create_access_token
from app.core.plan_features import TRIAL_DAYS, TRIAL_CREDITS
from app.routers.members import auto_accept_invites

router = APIRouter(prefix="/auth", tags=["auth"])


# ✅ CURRENT USER (used by frontend to render the avatar / greeting)
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


# ✅ REGISTER
@router.post("/register", response_model=TokenResponse)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    # Check if user already exists
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 🔹 Create user
    user = User(
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        full_name=user_data.full_name,
    )
    db.add(user)
    db.flush()  # ensures user.id is available

    # 🔹 Create team
    team = Team(
        name=f"{user.full_name or user.email}'s Team",
        owner_id=user.id
    )
    db.add(team)
    db.flush()

    # 🔹 Create wallet — start a 7-day trial with 1 credit. The download is
    #    blocked at the route level (see feature_guard's TRIAL config).
    wallet = CreditWallet(
        team_id=team.id,
        subscription_credits=TRIAL_CREDITS,
        purchased_credits=0,
        plan_type="TRIAL",
        subscription_status="TRIAL",
        subscription_expires_at=datetime.utcnow() + timedelta(days=TRIAL_DAYS),
    )
    db.add(wallet)

    # Mirror the trial state on the user record so the existing
    # user.subscription_plan / status fields stay consistent.
    user.subscription_plan = "TRIAL"
    user.subscription_status = "TRIAL"

    db.commit()
    db.refresh(user)

    # Auto-accept any pending team invites that were sent to this email.
    try:
        auto_accept_invites(db, user)
    except Exception:
        pass

    # 🔐 Create JWT
    token = create_access_token({"sub": str(user.id)})

    return TokenResponse(access_token=token)


# ✅ LOGIN
@router.post("/login", response_model=TokenResponse)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    # 🔐 Verify password
    if not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    # Auto-accept any pending team invites — covers users who already had an
    # account when they were invited.
    try:
        auto_accept_invites(db, user)
    except Exception:
        pass

    # 🔐 Create JWT
    token = create_access_token({"sub": str(user.id)})

    return TokenResponse(access_token=token)
