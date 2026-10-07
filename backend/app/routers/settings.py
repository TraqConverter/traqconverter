import logging
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.core.file_validation import validate_file_extension, validate_file_size
from app.dependencies.tenant import can_manage_team
from app.services.storage_service import save_certification_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.post("/upload-certification")
async def upload_certification(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_file_extension(file.filename)
    validate_file_size(file)

    file_path = None

    try:
        file_path = save_certification_file(file, str(current_user.id))

        current_user.certification_file = file_path
        db.commit()

        return {
            "message": "Certification uploaded successfully",
            "file_path": file_path
        }

    except Exception:
        db.rollback()

        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        raise HTTPException(
            status_code=400,
            detail="Certification upload failed"
        )


def _resolve_team(db: Session, user: User):
    """Look up the team this user owns or is a member of."""
    from app.models.team import Team
    from app.models.team_member import TeamMember

    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if team:
        return team
    membership = (
        db.query(TeamMember).filter(TeamMember.user_id == user.id).first()
    )
    if membership:
        team = db.query(Team).filter(Team.id == membership.team_id).first()
        if team:
            return team
    raise HTTPException(status_code=404, detail="No team found")


def _payments(db: Session, team, user: User, account=None) -> dict:
    from app.services import stripe_connect

    return {
        "paypal_me": team.paypal_me,
        "paypal_url": f"https://paypal.me/{team.paypal_me}" if team.paypal_me else None,
        "can_edit": can_manage_team(db, team, user),
        **stripe_connect.summary(team, account),
    }


def _editable_team(db: Session, user: User):
    team = _resolve_team(db, user)
    if not can_manage_team(db, team, user):
        raise HTTPException(status_code=403, detail="Only the team owner or an admin can change payment settings")
    return team


class _Payments(BaseModel):
    paypal_me: str | None = None


STRIPE_REFRESH_SECONDS = 300


@router.get("/payments")
def get_payment_settings(
    refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """`refresh` (back from Stripe onboarding) skips the throttle on asking Stripe for the account's status."""
    from datetime import datetime, timedelta

    from app.services import stripe_connect

    # Readable by the whole team: the share dialog shows the handle a protected link will use.
    team = _resolve_team(db, current_user)
    account = None
    if team.stripe_account_id and team.stripe_account_status != "active":
        # Onboarding may have just finished; the webhook can lag behind the redirect back here.
        now = datetime.utcnow()
        checked = team.stripe_account_checked_at
        due = checked is None or now - checked >= timedelta(seconds=STRIPE_REFRESH_SECONDS)
        if due or (refresh and can_manage_team(db, team, current_user)):
            team.stripe_account_checked_at = now
            db.commit()
            account = stripe_connect.refresh(db, team)
    return _payments(db, team, current_user, account)


@router.put("/payments")
def update_payment_settings(
    payload: _Payments,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.paypal import normalise_handle

    team = _resolve_team(db, current_user)
    if not can_manage_team(db, team, current_user):
        raise HTTPException(status_code=403, detail="Only the team owner or an admin can change payment settings")
    try:
        team.paypal_me = normalise_handle(payload.paypal_me)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    return _payments(db, team, current_user)


class _StripeConnect(BaseModel):
    country: str | None = None


@router.post("/payments/stripe/connect")
def connect_stripe(
    payload: _StripeConnect | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create the team's Stripe account if it has none, and return a Stripe onboarding link for it."""
    import re

    from app.services import stripe_connect

    team = _editable_team(db, current_user)
    country = (payload.country or "").strip().upper() if payload else ""
    if country and not re.fullmatch(r"[A-Z]{2}", country):
        raise HTTPException(status_code=422, detail="country must be a two-letter code")
    try:
        account_id = stripe_connect.ensure_account(db, team, current_user, country or None)
        url = stripe_connect.onboarding_url(account_id)
    except Exception as exc:
        db.rollback()
        logger.exception("Stripe Connect onboarding failed (team=%s)", team.id)
        code = exc.code if isinstance(exc, stripe_connect.StripeV2Error) else None
        if code in stripe_connect.COUNTRY_NOT_SUPPORTED:
            raise HTTPException(status_code=422, detail="Card payments aren't available for accounts in this country yet.")
        # Stripe refuses connected accounts until the platform owner finishes the Connect questionnaire.
        if code in stripe_connect.PLATFORM_NOT_READY or "to use connect" in str(exc).lower():
            raise HTTPException(
                status_code=503,
                detail="Card payments aren't available yet: the platform's Stripe setup isn't finished. Use the PayPal option for now.",
            )
        raise HTTPException(status_code=502, detail="Stripe isn't reachable right now. Try again in a minute.")
    return {"url": url}


@router.post("/payments/stripe/dashboard")
def stripe_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services import stripe_connect

    team = _editable_team(db, current_user)
    if not team.stripe_account_id:
        raise HTTPException(status_code=409, detail="Connect Stripe first")
    return {"url": stripe_connect.DASHBOARD_URL}


@router.delete("/payments/stripe")
def disconnect_stripe(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop taking card payments here. The Stripe account itself stays the translator's."""
    team = _editable_team(db, current_user)
    team.stripe_account_id = None
    team.stripe_account_status = None
    team.stripe_account_checked_at = None
    db.commit()
    return _payments(db, team, current_user)