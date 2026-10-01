import logging
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.core.file_validation import validate_file_extension, validate_file_size
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







@router.post("/upload-logo")
async def upload_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from pathlib import Path
    import tempfile
    from app.services.s3_service import upload_file_to_s3

    name = (file.filename or "").lower()
    if not name.endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(
            status_code=400, detail="Logo must be a PNG or JPG file."
        )



    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=400, detail="Logo file too large (2MB max)."
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="logo_"))
    tmp_path = tmp_dir / (file.filename or "logo.png")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        s3_key = upload_file_to_s3(tmp_path)
        current_user.logo_s3_key = s3_key
        db.commit()
        return {"message": "Logo uploaded", "logo_s3_key": s3_key}
    except Exception:
        logger.exception("Request failed")
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Logo upload failed"
        )
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@router.delete("/logo")
def delete_logo(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove the user's logo (cert page renders without a logo)."""
    current_user.logo_s3_key = None
    db.commit()
    return {"message": "Logo removed"}









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


@router.get("/stamp")
def get_stamp(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current team stamp info so the Settings UI can
    render a preview + show the chosen alignment."""
    from app.services.s3_service import generate_presigned_download_url

    team = _resolve_team(db, current_user)
    url = None
    if team.stamp_s3_key:
        try:
            url = generate_presigned_download_url(
                team.stamp_s3_key, inline=True
            )
        except Exception:
            url = None
    return {
        "has_stamp": bool(team.stamp_s3_key),
        "url": url,
        "alignment": team.stamp_alignment or "right",
    }


@router.post("/upload-stamp")
async def upload_stamp(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from pathlib import Path
    import tempfile
    from app.services.s3_service import upload_file_to_s3

    team = _resolve_team(db, current_user)

    name = (file.filename or "").lower()
    if not name.endswith((".png", ".jpg", ".jpeg")):
        raise HTTPException(
            status_code=400, detail="Stamp must be a PNG or JPG file."
        )
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=400, detail="Stamp file too large (2MB max)."
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="stamp_"))
    tmp_path = tmp_dir / (file.filename or "stamp.png")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        s3_key = upload_file_to_s3(tmp_path)
        team.stamp_s3_key = s3_key
        db.commit()
        db.refresh(team)
        return {"message": "Stamp uploaded", "stamp_s3_key": s3_key}
    except Exception:
        logger.exception("Request failed")
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Stamp upload failed"
        )
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


@router.delete("/stamp")
def delete_stamp(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_team(db, current_user)
    team.stamp_s3_key = None
    db.commit()
    return {"message": "Stamp removed"}


from pydantic import BaseModel


class _StampAlignment(BaseModel):
    alignment: str


@router.patch("/stamp-alignment")
def update_stamp_alignment(
    payload: _StampAlignment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    valid = {"left", "center", "right"}
    alignment = (payload.alignment or "").lower().strip()
    if alignment not in valid:
        raise HTTPException(
            status_code=400,
            detail="alignment must be one of: left, center, right",
        )
    team = _resolve_team(db, current_user)
    team.stamp_alignment = alignment
    db.commit()
    return {"alignment": team.stamp_alignment}


def _can_edit_team(db: Session, team, user: User) -> bool:
    from app.models.team_member import TeamMember

    if team.owner_id == user.id:
        return True
    member = db.query(TeamMember).filter(TeamMember.team_id == team.id, TeamMember.user_id == user.id).first()
    return bool(member and (member.role or "").upper() == "ADMIN")


def _payments(db: Session, team, user: User, account=None) -> dict:
    from app.services import stripe_connect

    return {
        "paypal_me": team.paypal_me,
        "paypal_url": f"https://paypal.me/{team.paypal_me}" if team.paypal_me else None,
        "can_edit": _can_edit_team(db, team, user),
        **stripe_connect.summary(team, account),
    }


def _editable_team(db: Session, user: User):
    team = _resolve_team(db, user)
    if not _can_edit_team(db, team, user):
        raise HTTPException(status_code=403, detail="Only the team owner or an admin can change payment settings")
    return team


class _Payments(BaseModel):
    paypal_me: str | None = None


@router.get("/payments")
def get_payment_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services import stripe_connect

    # Readable by the whole team: the share dialog shows the handle a protected link will use.
    team = _resolve_team(db, current_user)
    account = None
    if team.stripe_account_id and team.stripe_account_status != "active":
        # Onboarding may have just finished; the webhook can lag behind the redirect back here.
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
    if not _can_edit_team(db, team, current_user):
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
    except Exception:
        db.rollback()
        logger.exception("Stripe Connect onboarding failed (team=%s)", team.id)
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
    db.commit()
    return _payments(db, team, current_user)