import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

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
        "logo_s3_key": getattr(current_user, "logo_s3_key", None),
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
    """Permanently delete the user's account.

    For an OWNER, this also tears down their team and every artefact
    attached to it — projects, segments, comments, job queue rows,
    translation memory, glossary entries, members, invites, credit
    wallet + transactions, stripe event log entries.

    For a non-owner (a team member), we only remove their User row +
    their TeamMember rows. The team and its data stay with the owner.

    Each step uses synchronize_session=False bulk deletes so the
    session doesn't get out of sync with the database. We walk
    children → parents so FK constraints don't block any step.
    """
    from sqlalchemy import text
    from app.models.team_member import TeamMember, TeamInvite
    from app.models.translation_segment import TranslationSegment
    from app.models.segment_comment import SegmentComment
    from app.models.project import TranslationProject
    from app.models.credit import CreditWallet, CreditTransaction

    if payload.confirm.strip().upper() != "DELETE":
        raise HTTPException(
            status_code=400, detail='Type "DELETE" to confirm account deletion'
        )
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect")

    user_id = current_user.id
    team = db.query(Team).filter(Team.owner_id == user_id).first()

    try:
        if team is not None:
            team_id = team.id

            # 1) Fetch project IDs once so we can purge their children
            #    in bulk.
            project_ids = [
                row[0]
                for row in db.query(TranslationProject.id)
                .filter(TranslationProject.team_id == team_id)
                .all()
            ]

            if project_ids:
                segment_ids = [
                    row[0]
                    for row in db.query(TranslationSegment.id)
                    .filter(TranslationSegment.project_id.in_(project_ids))
                    .all()
                ]
                if segment_ids:
                    db.query(SegmentComment).filter(
                        SegmentComment.segment_id.in_(segment_ids)
                    ).delete(synchronize_session=False)
                db.query(TranslationSegment).filter(
                    TranslationSegment.project_id.in_(project_ids)
                ).delete(synchronize_session=False)

                # translation_jobs + translation_memory are raw-SQL
                # tables; not all deployments have project_id on TM.
                for sql, params in (
                    (
                        "DELETE FROM translation_jobs WHERE project_id = ANY(:pids)",
                        {"pids": [str(p) for p in project_ids]},
                    ),
                    (
                        "DELETE FROM translation_memory WHERE project_id = ANY(:pids)",
                        {"pids": [str(p) for p in project_ids]},
                    ),
                ):
                    try:
                        db.execute(text(sql), params)
                    except Exception:
                        db.rollback()
                        # Re-attach team object after rollback so we
                        # can keep going.
                        team = db.query(Team).filter(
                            Team.id == team_id
                        ).first()

                db.query(TranslationProject).filter(
                    TranslationProject.team_id == team_id
                ).delete(synchronize_session=False)

            # 2) Team-level scoped collections.
            db.query(TeamMember).filter(
                TeamMember.team_id == team_id
            ).delete(synchronize_session=False)
            db.query(TeamInvite).filter(
                TeamInvite.team_id == team_id
            ).delete(synchronize_session=False)

            # Team-scoped glossary entries (table is raw-SQL backed).
            try:
                db.execute(
                    text("DELETE FROM glossary WHERE team_id = :tid"),
                    {"tid": str(team_id)},
                )
            except Exception:
                db.rollback()
                team = db.query(Team).filter(Team.id == team_id).first()

            # 3) Wallet + transactions.
            wallet_ids = [
                row[0]
                for row in db.query(CreditWallet.id)
                .filter(CreditWallet.team_id == team_id)
                .all()
            ]
            if wallet_ids:
                db.query(CreditTransaction).filter(
                    CreditTransaction.wallet_id.in_(wallet_ids)
                ).delete(synchronize_session=False)
                db.query(CreditWallet).filter(
                    CreditWallet.team_id == team_id
                ).delete(synchronize_session=False)

            # 4) Finally the team row.
            db.execute(
                text("DELETE FROM teams WHERE id = :tid"),
                {"tid": str(team_id)},
            )

        # User may also be a MEMBER of other teams — drop those memberships.
        db.query(TeamMember).filter(
            TeamMember.user_id == user_id
        ).delete(synchronize_session=False)

        # And any stripe_event rows tied to them, just in case.
        try:
            db.execute(
                text(
                    "DELETE FROM stripe_events "
                    "WHERE user_id = :uid OR customer_email = :email"
                ),
                {"uid": str(user_id), "email": current_user.email},
            )
        except Exception:
            db.rollback()

        # 5) The user row.
        db.execute(
            text("DELETE FROM users WHERE id = :uid"),
            {"uid": str(user_id)},
        )

        db.commit()
    except Exception as e:
        logger.exception("Account delete failed: %s", e)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Couldn't delete account — {type(e).__name__}",
        )

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
    from app.models.team_member import TeamInvite

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

    # If this email already has a pending team invite, the user is
    # joining someone ELSE's team — they don't get their own team or
    # their own wallet, they inherit the inviter's team's wallet
    # (which determines their plan tier and credit pool). This is
    # what makes "invited members are on the same plan as the owner"
    # work transparently.
    pending_invite = (
        db.query(TeamInvite)
        .filter(
            TeamInvite.email == (user_data.email or "").lower(),
            TeamInvite.status == "PENDING",
        )
        .first()
    )

    if pending_invite is None:
        # Standalone register: create their own team and a trial wallet.
        team = Team(
            name=f"{user.full_name or user.email}'s Team",
            owner_id=user.id,
        )
        db.add(team)
        db.flush()

        # 7-day trial with 1 credit. Download is gated at the route
        # level (feature_guard's TRIAL config).
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
    else:
        # Invited user — mirror the owner's plan onto their User row
        # so /auth/me reflects the right tier. The wallet they share
        # with the team is the team-scoped CreditWallet, which they
        # don't get their own copy of.
        team_owner = (
            db.query(User)
            .join(Team, Team.owner_id == User.id)
            .filter(Team.id == pending_invite.team_id)
            .first()
        )
        if team_owner:
            user.subscription_plan = team_owner.subscription_plan or "TRIAL"
            user.subscription_status = team_owner.subscription_status or "TRIAL"
        else:
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
