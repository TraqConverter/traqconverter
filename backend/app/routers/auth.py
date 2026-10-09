import hashlib
import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.rate_limit import _hit, client_ip, rate_limit
from app.models.user import User
from app.models.team import Team
from app.models.credit import CreditTransaction, CreditWallet
from app.models.password_reset import PasswordResetToken
from app.schemas.auth import ForgotPassword, ResetPassword, UserRegister, UserLogin, TokenResponse
from app.services import email_service, owner_notifications
from app.core.security import hash_password, verify_password, create_access_token
from app.core.plan_features import TRIAL_DAYS, TRIAL_CREDITS
from app.routers.members import auto_accept_invites

router = APIRouter(prefix="/auth", tags=["auth"])




_login_limit = rate_limit("auth_login", max_requests=10, per_seconds=60)
_register_limit = rate_limit("auth_register", max_requests=5, per_seconds=300)





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

    current_user.token_version = (
        int(getattr(current_user, "token_version", 0) or 0) + 1
    )
    db.commit()
    db.refresh(current_user)



    new_token = create_access_token(
        {"sub": str(current_user.id)},
        token_version=int(current_user.token_version),
    )
    return {"status": "password_updated", "access_token": new_token}


def _user_by_email(db: Session, email: str):
    """Emails match case-insensitively; an exact match wins for older accounts differing only in case."""
    return (
        db.query(User)
        .filter(func.lower(User.email) == email.lower())
        .order_by((User.email == email).desc())
        .first()
    )


RESET_TOKEN_MINUTES = 60
FORGOT_MESSAGE = "If an account exists for that email, we've sent a reset link."
INVALID_RESET_MESSAGE = "This reset link is invalid or has expired."

_forgot_ip_limit = rate_limit("auth_forgot", max_requests=5, per_seconds=3600)
_reset_ip_limit = rate_limit("auth_reset", max_requests=10, per_seconds=900)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _invalidate_reset_tokens(db: Session, user_id, now: datetime) -> None:
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)


def _send_reset_email(to: str, name: str | None, link: str) -> None:
    subject, html = email_service.render_password_reset_email(name=name, link=link)
    text = (
        f"Reset your OnlineDocTranslator password: {link}\n\n"
        "This link expires in 60 minutes.\n"
        "If you didn't ask for this, you can ignore this email."
    )
    email_service.send_email(to=to, subject=subject, html=html, text_fallback=text)


@router.post("/forgot-password", dependencies=[Depends(_forgot_ip_limit)])
def forgot_password(
    payload: ForgotPassword,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    email = payload.email.strip().lower()
    _hit((f"email:{email}", "auth_forgot_email"), max_requests=5, per_seconds=3600)

    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None or user.is_active is False:
        return {"message": FORGOT_MESSAGE}

    now = datetime.utcnow()
    _invalidate_reset_tokens(db, user.id, now)
    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_reset_token(token),
        created_at=now,
        expires_at=now + timedelta(minutes=RESET_TOKEN_MINUTES),
        request_ip=client_ip(request)[:64],
    ))
    db.commit()

    if not email_service.is_configured():
        logger.warning("Password reset requested but email is not configured (RESEND_API_KEY missing); no email sent")
        return {"message": FORGOT_MESSAGE}

    link = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?{urlencode({'token': token})}"
    # Sent after the response so known and unknown emails answer in the same time.
    background_tasks.add_task(_send_reset_email, user.email, user.full_name, link)
    return {"message": FORGOT_MESSAGE}


@router.post("/reset-password", dependencies=[Depends(_reset_ip_limit)])
def reset_password(payload: ResetPassword, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == _hash_reset_token(payload.token))
        .with_for_update()
        .first()
    )
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise HTTPException(status_code=400, detail=INVALID_RESET_MESSAGE)
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None or user.is_active is False:
        raise HTTPException(status_code=400, detail=INVALID_RESET_MESSAGE)

    user.password_hash = hash_password(payload.new_password)
    # Signs out every existing session (JWTs carry the token version).
    user.token_version = int(user.token_version or 0) + 1
    # The emailed link proves who they are, so a lockout from someone else's guessing ends here.
    _clear_login_failures(user)
    _invalidate_reset_tokens(db, user.id, now)
    db.commit()
    return {"status": "password_updated"}










@router.post("/logout")
def logout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.token_version = (
        int(getattr(current_user, "token_version", 0) or 0) + 1
    )
    db.commit()
    return {"status": "logged_out"}





class DeleteAccount(BaseModel):
    password: str
    confirm: str


def _stored_files(db: Session, team_id, user) -> list:
    """Every storage key that belongs to the account, so deleting it also deletes the files."""
    from sqlalchemy import text

    keys = [getattr(user, "logo_s3_key", None)]
    if team_id is None:
        return [k for k in keys if k]
    queries = [
        "SELECT file_path, output_file, authored_docx_s3_key FROM translation_projects WHERE team_id = :tid",
        "SELECT v.s3_key FROM document_versions v JOIN translation_projects p ON p.id = v.project_id WHERE p.team_id = :tid",
        "SELECT l.file_key FROM delivery_links l JOIN translation_projects p ON p.id = l.project_id WHERE p.team_id = :tid",
        "SELECT jsonb_array_elements_text(l.preview_keys) FROM delivery_links l"
        " JOIN translation_projects p ON p.id = l.project_id WHERE p.team_id = :tid AND l.preview_keys IS NOT NULL",
        "SELECT s3_key FROM document_templates WHERE team_id = :tid",
        "SELECT file_path FROM certifications WHERE team_id = :tid",
        "SELECT stamp_s3_key FROM teams WHERE id = :tid",
        "SELECT s3_key FROM media_assets WHERE team_id = :tid",
        "SELECT original_key, translation_key FROM template_uploads WHERE team_id = :tid",
    ]
    for sql in queries:
        try:
            with db.begin_nested():
                for row in db.execute(text(sql), {"tid": str(team_id)}):
                    keys.extend(row)
        except Exception as e:
            logger.info("Storage key lookup skipped (%s): %s", sql.split(" FROM ")[1].split()[0], e)
    return [k for k in keys if k]


def _cancel_team_subscriptions(db: Session, team) -> None:
    """Stop billing before the team is deleted; 502 (and nothing deleted) if Stripe can't confirm."""
    import stripe

    from app.services.stripe_billing import team_subscription_ids

    for sub_id in team_subscription_ids(db, team):
        try:
            stripe.Subscription.cancel(sub_id)
        except stripe.error.InvalidRequestError as e:
            # Already cancelled, or no longer exists.
            logger.info("Subscription %s not cancelled on account delete: %s", sub_id, e)
        except Exception:
            logger.exception("Couldn't cancel subscription %s on account delete", sub_id)
            raise HTTPException(
                status_code=502,
                detail="Couldn't cancel your subscription with Stripe, so nothing was deleted. Try again in a minute.",
            )


def _hand_billing_to_owners(db: Session, user) -> None:
    """A member who started the team's subscription leaves it with the owner, so renewals and the portal still work."""
    if not (user.stripe_subscription_id or user.stripe_customer_id):
        return
    from app.models.team_member import TeamMember

    owners = (
        db.query(User)
        .join(Team, Team.owner_id == User.id)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .filter(TeamMember.user_id == user.id, User.id != user.id)
        .all()
    )
    for owner in owners:
        if user.stripe_subscription_id and not owner.stripe_subscription_id:
            owner.stripe_subscription_id = user.stripe_subscription_id
            owner.subscription_status = user.subscription_status
            owner.subscription_plan = user.subscription_plan
        if user.stripe_customer_id and not owner.stripe_customer_id:
            owner.stripe_customer_id = user.stripe_customer_id


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
    An owner's Stripe subscription is cancelled first.

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
    stored_keys = _stored_files(db, team.id if team is not None else None, current_user)
    if team is not None:
        _cancel_team_subscriptions(db, team)

    try:
        if team is None:
            _hand_billing_to_owners(db, current_user)
        if team is not None:
            team_id = team.id



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







                try:
                    with db.begin_nested():
                        db.execute(
                            text(
                                "DELETE FROM translation_jobs "
                                "WHERE project_id = ANY(:pids)"
                            ),
                            {"pids": [str(p) for p in project_ids]},
                        )
                except Exception as e:
                    logger.info("Optional translation_jobs cleanup skipped: %s", e)

                try:
                    with db.begin_nested():
                        db.execute(
                            text(
                                "DELETE FROM translation_memory "
                                "WHERE team_id = :tid"
                            ),
                            {"tid": str(team_id)},
                        )
                except Exception as e:


                    logger.info(
                        "TM team_id cleanup didn't apply, trying project_id: %s",
                        e,
                    )
                    try:
                        with db.begin_nested():
                            db.execute(
                                text(
                                    "DELETE FROM translation_memory "
                                    "WHERE project_id = ANY(:pids)"
                                ),
                                {"pids": [str(p) for p in project_ids]},
                            )
                    except Exception as e2:
                        logger.info("TM project_id cleanup also skipped: %s", e2)

                db.query(TranslationProject).filter(
                    TranslationProject.team_id == team_id
                ).delete(synchronize_session=False)


            db.query(TeamMember).filter(
                TeamMember.team_id == team_id
            ).delete(synchronize_session=False)
            db.query(TeamInvite).filter(
                TeamInvite.team_id == team_id
            ).delete(synchronize_session=False)




            try:
                with db.begin_nested():
                    db.execute(
                        text("DELETE FROM glossary WHERE team_id = :tid"),
                        {"tid": str(team_id)},
                    )
            except Exception as e:
                logger.info("Optional glossary cleanup skipped: %s", e)


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


            db.execute(
                text("DELETE FROM teams WHERE id = :tid"),
                {"tid": str(team_id)},
            )


        db.query(TeamMember).filter(
            TeamMember.user_id == user_id
        ).delete(synchronize_session=False)

        # Work in other teams stays there: their owner becomes the uploader, and comments lose their author.
        db.execute(
            text(
                "UPDATE translation_projects p SET user_id = t.owner_id "
                "FROM teams t WHERE p.team_id = t.id AND p.user_id = :uid"
            ),
            {"uid": str(user_id)},
        )
        db.execute(
            text("UPDATE segment_comments SET user_id = NULL WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )




        try:
            with db.begin_nested():
                db.execute(
                    text(
                        "DELETE FROM stripe_events "
                        "WHERE user_id = :uid OR customer_email = :email"
                    ),
                    {"uid": str(user_id), "email": current_user.email},
                )
        except Exception as e:
            logger.info("Optional stripe_events cleanup skipped: %s", e)


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
            detail="Couldn't delete account",
        )

    from app.services.s3_service import delete_objects_from_s3

    delete_objects_from_s3(stored_keys)
    return {"status": "deleted"}





@router.post(
    "/register",
    response_model=TokenResponse,
    dependencies=[Depends(_register_limit)],
)
def register(user_data: UserRegister, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    from app.models.team_member import TeamInvite

    if _user_by_email(db, user_data.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=user_data.email.lower(),
        password_hash=hash_password(user_data.password),
        full_name=user_data.full_name,
        terms_accepted_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()







    pending_invite = (
        db.query(TeamInvite)
        .filter(
            TeamInvite.email == (user_data.email or "").lower(),
            TeamInvite.status == "PENDING",
            TeamInvite.token == user_data.invite_token,
        )
        .first()
        if user_data.invite_token
        else None
    )

    if pending_invite is None:

        team = Team(
            name=f"{user.full_name or user.email}'s Team",
            owner_id=user.id,
        )
        db.add(team)
        db.flush()



        wallet = CreditWallet(
            team_id=team.id,
            subscription_credits=TRIAL_CREDITS,
            purchased_credits=0,
            plan_type="TRIAL",
            subscription_status="TRIAL",
            subscription_expires_at=datetime.utcnow() + timedelta(days=TRIAL_DAYS),
        )
        db.add(wallet)
        db.flush()
        db.add(CreditTransaction(
            wallet_id=wallet.id, type="TRIAL_GRANT", amount=TRIAL_CREDITS, reference_id="trial",
        ))

        user.subscription_plan = "TRIAL"
        user.subscription_status = "TRIAL"
    else:




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

    signup_team_id = pending_invite.team_id if pending_invite is not None else team.id
    db.commit()
    db.refresh(user)

    if pending_invite is not None:
        auto_accept_invites(db, user, user_data.invite_token)

    owner_notifications.notify(
        background_tasks, "signup", owner_notifications.signup, db, user, signup_team_id, pending_invite is not None
    )


    token = create_access_token(
        {"sub": str(user.id)},
        token_version=int(getattr(user, "token_version", 0) or 0),
    )
    return TokenResponse(access_token=token)





LOGIN_MAX_FAILURES = 10
LOGIN_FAILURE_WINDOW = timedelta(minutes=15)
LOGIN_LOCKOUT = timedelta(minutes=15)


def _clear_login_failures(user: User) -> None:
    user.failed_login_count = 0
    user.failed_login_window_start = None
    user.login_locked_until = None


def _record_failed_login(db: Session, user_id, now: datetime) -> None:
    # Row-locked so parallel guesses can't each read the same count.
    user = db.query(User).filter(User.id == user_id).with_for_update().populate_existing().one()
    start = user.failed_login_window_start
    if start is None or now - start > LOGIN_FAILURE_WINDOW:
        user.failed_login_window_start = now
        user.failed_login_count = 1
    else:
        user.failed_login_count = int(user.failed_login_count or 0) + 1
    if user.failed_login_count >= LOGIN_MAX_FAILURES:
        user.login_locked_until = now + LOGIN_LOCKOUT
        user.failed_login_count = 0
        user.failed_login_window_start = None
    db.commit()


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(_login_limit)],
)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = _user_by_email(db, user_data.email)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    now = datetime.utcnow()
    password_ok = verify_password(user_data.password, user.password_hash)
    # A locked account gets the wrong-password answer even with the right password, so the lock reveals nothing.
    if user.login_locked_until and user.login_locked_until > now:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    if not password_ok:
        _record_failed_login(db, user.id, now)
        raise HTTPException(status_code=400, detail="Invalid credentials")
    if user.failed_login_count or user.login_locked_until:
        _clear_login_failures(user)
        db.commit()

    # Same answer as a wrong password, so a deactivated account can't be told apart.
    if user.is_active is False:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = create_access_token(
        {"sub": str(user.id)},
        token_version=int(getattr(user, "token_version", 0) or 0),
    )
    return TokenResponse(access_token=token)
