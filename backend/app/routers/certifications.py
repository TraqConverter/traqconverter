import hashlib
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.models.user import User
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.certification import Certification
from app.core.file_validation import validate_file_extension, validate_file_size


router = APIRouter(
    prefix="/certifications",
    tags=["Certifications"],
    dependencies=[Depends(require_feature("certifications"))],
)


ALLOWED_KINDS = {"AFFIDAVIT", "ISO_17100", "SWORN_DECLARATION", "OTHER"}
BASE_DIR = "uploads/certifications"


# ============================================================
# Helpers
# ============================================================

def _resolve_team(db: Session, user: User) -> Team:
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


def _serialize(c: Certification, uploader_email: Optional[str] = None) -> dict:
    return {
        "id": str(c.id),
        "file_name": c.file_name,
        "kind": c.kind,
        "notes": c.notes,
        "file_hash": c.file_hash,
        "size_bytes": c.size_bytes,
        "mime_type": c.mime_type,
        "uploaded_at": c.uploaded_at.isoformat() if c.uploaded_at else None,
        "uploaded_by": str(c.uploaded_by) if c.uploaded_by else None,
        "uploader_email": uploader_email,
    }


# ============================================================
# LIST
# ============================================================

@router.get("")
def list_certifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_team(db, current_user)
    rows = (
        db.query(Certification)
        .filter(Certification.team_id == team.id)
        .order_by(Certification.uploaded_at.desc())
        .all()
    )

    # Pre-fetch uploader emails so the UI can show who uploaded each file.
    uploader_ids = {r.uploaded_by for r in rows if r.uploaded_by}
    uploaders: dict[str, str] = {}
    if uploader_ids:
        for u in db.query(User).filter(User.id.in_(uploader_ids)).all():
            uploaders[str(u.id)] = u.email

    return {
        "team_id": str(team.id),
        "items": [
            _serialize(r, uploaders.get(str(r.uploaded_by)) if r.uploaded_by else None)
            for r in rows
        ],
    }


# ============================================================
# UPLOAD
# ============================================================

@router.post("/upload")
async def upload_certification(
    file: UploadFile = File(...),
    kind: str = Form("OTHER"),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a certification template / signed affidavit / ISO 17100 cert.

    Storage strategy: upload to Supabase Storage (S3-compatible) so
    the file survives Railway redeploys. We store the storage KEY in
    ``cert.file_path`` — the download endpoint hands back a signed
    URL that the frontend can follow.

    Local disk was the old behaviour and is the reason previously-
    uploaded certs vanished after a redeploy with "Couldn't download
    that file."
    """
    import tempfile
    from pathlib import Path as _Path
    from app.services.s3_service import upload_file_to_s3

    validate_file_extension(file.filename)
    validate_file_size(file)

    kind_upper = kind.strip().upper()
    if kind_upper not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="Invalid certification kind")

    team = _resolve_team(db, current_user)

    raw = await file.read()
    file_hash = hashlib.sha256(raw).hexdigest()

    # Write to a temp file so we can hand a Path to upload_file_to_s3
    # (the helper takes Path because the project upload flow uses one).
    tmp_path: Optional[_Path] = None
    s3_key: Optional[str] = None
    try:
        suffix = ""
        if file.filename and "." in file.filename:
            suffix = "." + file.filename.rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = _Path(tmp.name)
        # Give it a friendlier name so the storage key is identifiable.
        # upload_file_to_s3 uses the input Path's `.name`.
        renamed = tmp_path.with_name(file.filename or tmp_path.name)
        try:
            tmp_path.rename(renamed)
            tmp_path = renamed
        except Exception:
            pass
        s3_key = upload_file_to_s3(tmp_path)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Couldn't upload certification: {e}"
        )
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    cert = Certification(
        team_id=team.id,
        uploaded_by=current_user.id,
        file_name=file.filename,
        file_path=s3_key,
        kind=kind_upper,
        notes=(notes or "").strip() or None,
        file_hash=file_hash,
        size_bytes=len(raw),
        mime_type=file.content_type,
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)

    return _serialize(cert, current_user.email)


# ============================================================
# DOWNLOAD
# ============================================================

@router.get("/{cert_id}/download")
def download_certification(
    cert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hand the client a short-lived signed URL to the cert file.

    The frontend opens this URL in a new tab / triggers download from
    it. Storing the file in Supabase means it survives container
    restarts (the old local-disk behaviour was why downloads broke
    after every redeploy).
    """
    from app.services.s3_service import generate_presigned_download_url
    from fastapi.responses import RedirectResponse

    team = _resolve_team(db, current_user)
    cert = (
        db.query(Certification)
        .filter(Certification.id == cert_id, Certification.team_id == team.id)
        .first()
    )
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")
    if not cert.file_path:
        raise HTTPException(status_code=410, detail="File missing")

    # Legacy local-disk path — keep working for any cert uploaded
    # before the Supabase migration.
    if os.path.exists(cert.file_path) and os.path.isfile(cert.file_path):
        return FileResponse(
            cert.file_path,
            filename=cert.file_name,
            media_type=cert.mime_type or "application/octet-stream",
        )

    # New Supabase path — file_path holds the storage key.
    try:
        url = generate_presigned_download_url(cert.file_path)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Couldn't generate download link: {e}"
        )
    return RedirectResponse(url=url, status_code=307)


# ============================================================
# SCAN — detect {{token}} placeholders in a template DOCX so the
# upload UI can show the user which fields will be auto-filled.
# ============================================================

@router.get("/{cert_id}/scan")
def scan_certification(
    cert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.cert_template_service import scan_docx_for_tokens

    team = _resolve_team(db, current_user)
    cert = (
        db.query(Certification)
        .filter(Certification.id == cert_id, Certification.team_id == team.id)
        .first()
    )
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    name = (cert.file_name or "").lower()
    if not name.endswith(".docx"):
        return {
            "is_template": False,
            "reason": (
                "Only .docx templates support placeholder substitution. "
                "Re-upload as DOCX to enable dynamic fields."
            ),
            "found": [],
            "unknown": [],
            "supported": [],
        }

    # Two storage paths to support: legacy local disk + new Supabase.
    docx_bytes: bytes = b""
    if cert.file_path and os.path.exists(cert.file_path) and os.path.isfile(cert.file_path):
        with open(cert.file_path, "rb") as f:
            docx_bytes = f.read()
    else:
        try:
            from app.services.s3_service import (
                generate_presigned_download_url,
            )
            import requests as _req
            url = generate_presigned_download_url(cert.file_path)
            r = _req.get(url, timeout=15)
            r.raise_for_status()
            docx_bytes = r.content
        except Exception as e:
            raise HTTPException(
                status_code=410,
                detail=f"Couldn't fetch template from storage: {e}",
            )

    scan = scan_docx_for_tokens(docx_bytes)
    scan["is_template"] = bool(scan.get("found") or scan.get("unknown"))
    return scan


# ============================================================
# PREVIEW SUPPORTED FIELDS — UI can call this on the upload screen
# (before any cert is saved) to show what tokens are available.
# ============================================================

@router.get("/template-fields")
def template_fields():
    from app.services.cert_template_service import SUPPORTED_FIELDS

    return {
        "fields": [
            {"name": name, "description": desc}
            for name, desc in SUPPORTED_FIELDS
        ]
    }


# ============================================================
# DELETE
# ============================================================

@router.delete("/{cert_id}")
def delete_certification(
    cert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _resolve_team(db, current_user)
    cert = (
        db.query(Certification)
        .filter(Certification.id == cert_id, Certification.team_id == team.id)
        .first()
    )
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    # Only the team owner or the uploader can delete
    is_owner = team.owner_id == current_user.id
    is_uploader = cert.uploaded_by == current_user.id
    if not (is_owner or is_uploader):
        raise HTTPException(status_code=403, detail="You can't remove this file")

    file_path = cert.file_path
    db.delete(cert)
    db.commit()

    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass  # row is gone; orphaned file isn't fatal

    return {"status": "deleted"}
