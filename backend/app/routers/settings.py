from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.core.file_validation import validate_file_extension, validate_file_size
from app.services.storage_service import save_certification_file

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


# ============================================================
# Company logo upload — appears at the top of the certification page
# on every exported translation. Each user has their own logo. PNG or
# JPG, max ~2MB.
# ============================================================
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

    # Save to a temp file then push to S3 using the same path as
    # uploaded project files. ~2MB cap so users can't push huge images.
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
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Logo upload failed: {e}"
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


# ============================================================
# COMPANY STAMP — team-scoped image overlaid at the bottom of every
# translated rebuild page (NOT on the embedded original pages).
# Each team picks alignment (left / center / right) to match their
# letterhead style.
# ============================================================

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
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Stamp upload failed: {e}"
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