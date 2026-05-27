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
    validate_file_extension(file.filename)
    validate_file_size(file)

    kind_upper = kind.strip().upper()
    if kind_upper not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="Invalid certification kind")

    team = _resolve_team(db, current_user)

    # Save the file
    directory = os.path.join(BASE_DIR, str(team.id))
    os.makedirs(directory, exist_ok=True)

    # Prefix with a uuid so two uploads with the same filename can coexist
    safe_id = uuid.uuid4().hex[:8]
    safe_name = f"{safe_id}_{file.filename}"
    file_path = os.path.join(directory, safe_name)

    raw = await file.read()
    file_hash = hashlib.sha256(raw).hexdigest()

    try:
        with open(file_path, "wb") as f:
            f.write(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Couldn't save file: {e}")

    cert = Certification(
        team_id=team.id,
        uploaded_by=current_user.id,
        file_name=file.filename,
        file_path=file_path,
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
    team = _resolve_team(db, current_user)
    cert = (
        db.query(Certification)
        .filter(Certification.id == cert_id, Certification.team_id == team.id)
        .first()
    )
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    if not os.path.exists(cert.file_path):
        raise HTTPException(status_code=410, detail="File missing on disk")

    return FileResponse(
        cert.file_path,
        filename=cert.file_name,
        media_type=cert.mime_type or "application/octet-stream",
    )


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
    if not os.path.exists(cert.file_path):
        raise HTTPException(status_code=410, detail="File missing on disk")

    with open(cert.file_path, "rb") as f:
        docx_bytes = f.read()
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
