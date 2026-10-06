import logging
import hashlib
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
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


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/certifications",
    tags=["Certifications"],
    dependencies=[Depends(require_feature("certifications"))],
)


# Old clients sent a user-chosen kind; still accepted, never required.
LEGACY_KINDS = {"AFFIDAVIT", "ISO_17100", "SWORN_DECLARATION", "OTHER", "TEMPLATE"}
BASE_DIR = "uploads/certifications"






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


def _is_docx_name(name: Optional[str]) -> bool:
    return (name or "").lower().endswith(".docx")


def _kind_for(file_name: Optional[str], kind: Optional[str]) -> str:
    given = (kind or "").strip().upper()
    if given in LEGACY_KINDS:
        return given
    return "TEMPLATE" if _is_docx_name(file_name) else "OTHER"


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
        "is_default": bool(c.is_default),
        "is_template": _is_docx_name(c.file_name),
    }






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






@router.post("/upload")
async def upload_certification(
    file: UploadFile = File(...),
    kind: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a Word certification template or a supporting file.

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

    team = _resolve_team(db, current_user)

    raw = await file.read()
    file_hash = hashlib.sha256(raw).hexdigest()



    tmp_path: Optional[_Path] = None
    s3_key: Optional[str] = None
    try:
        suffix = ""
        if file.filename and "." in file.filename:
            suffix = "." + file.filename.rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = _Path(tmp.name)


        renamed = tmp_path.with_name(file.filename or tmp_path.name)
        try:
            tmp_path.rename(renamed)
            tmp_path = renamed
        except Exception:
            pass
        s3_key = upload_file_to_s3(tmp_path)
    except Exception:
        logger.exception("Request failed")
        raise HTTPException(
            status_code=500, detail="Couldn't upload certification"
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
        kind=_kind_for(file.filename, kind),
        notes=(notes or "").strip() or None,
        file_hash=file_hash,
        size_bytes=len(raw),
        mime_type=file.content_type,
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)

    return _serialize(cert, current_user.email)






def _team_cert(db: Session, user: User, cert_id: str) -> tuple[Team, Certification]:
    team = _resolve_team(db, user)
    try:
        cert_uuid = uuid.UUID(cert_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Certification not found")
    cert = (
        db.query(Certification)
        .filter(Certification.id == cert_uuid, Certification.team_id == team.id)
        .first()
    )
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")
    return team, cert


@router.get("/{cert_id}/download-url")
def certification_download_url(
    cert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A signed storage link the browser navigates to; an XHR can't follow the storage redirect (CORS)."""
    from app.services.s3_service import generate_presigned_download_url, object_exists

    _, cert = _team_cert(db, current_user, cert_id)
    if not cert.file_path:
        raise HTTPException(status_code=410, detail="File missing")
    if os.path.isfile(cert.file_path):
        return {"url": None, "file_name": cert.file_name}
    if not object_exists(cert.file_path):
        raise HTTPException(status_code=404, detail="This file is no longer available")
    try:
        url = generate_presigned_download_url(cert.file_path, filename=cert.file_name)
    except Exception:
        logger.exception("Couldn't sign certification download")
        raise HTTPException(status_code=500, detail="Couldn't generate download link")
    return {"url": url, "file_name": cert.file_name}


class _DefaultFlag(BaseModel):
    is_default: bool = True


@router.put("/{cert_id}/default")
def set_default_template(
    cert_id: str,
    payload: _DefaultFlag,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team, cert = _team_cert(db, current_user, cert_id)
    make_default = payload.is_default
    if make_default and not (cert.file_name or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only Word (.docx) templates can be the default")
    if make_default:
        db.query(Certification).filter(
            Certification.team_id == team.id, Certification.id != cert.id, Certification.is_default.is_(True)
        ).update({Certification.is_default: False}, synchronize_session=False)
        db.flush()
    cert.is_default = make_default
    db.commit()
    return _serialize(cert)


def _template_check(db: Session, user: User, cert_id: str):
    from app.services import cert_page, docx_cert_template, docx_certification
    from app.services.docx_blocks import DocxEditError

    team, cert = _team_cert(db, user, cert_id)
    if not (cert.file_name or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only Word (.docx) templates can be checked")
    try:
        raw = cert_page.load_bytes(cert)
    except Exception:
        logger.exception("Couldn't load certification template %s", cert.id)
        raise HTTPException(status_code=502, detail="Couldn't load the template from storage")
    content = cert_page.example_content(db, user, team, raw)
    report = docx_cert_template.TemplateReport()
    try:
        preview = docx_certification.standalone(content, report, page_break=False)
    except DocxEditError as e:
        raise HTTPException(status_code=422, detail=str(e) or "The template couldn't be read")
    return content, report, preview


@router.get("/{cert_id}/check")
def check_template(
    cert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services import cert_fields

    content, report, _ = _template_check(db, current_user, cert_id)
    return {
        "fields": [
            {
                **f,
                "label": cert_fields.LABELS.get(f["field"], f["field"]),
                "value": content.values.get(f["field"], content.extra_tokens.get(f["field"], "")),
            }
            for f in report.fields
        ],
        "unknown": report.unknown,
        "dropped": [{"what": k, "count": v} for k, v in report.dropped.items()],
        "notes": report.notes,
        "example": {"document": content.values["document"], "file_name": content.values["file_name"]},
    }


@router.get("/{cert_id}/preview")
def preview_template(
    cert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from fastapi.responses import Response

    from app.services.docx_blocks import strip_blocks

    _, _, preview = _template_check(db, current_user, cert_id)
    return Response(
        content=strip_blocks(preview),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Cache-Control": "no-store"},
    )


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



    if os.path.exists(cert.file_path) and os.path.isfile(cert.file_path):
        return FileResponse(
            cert.file_path,
            filename=cert.file_name,
            media_type=cert.mime_type or "application/octet-stream",
        )


    try:
        url = generate_presigned_download_url(cert.file_path)
    except Exception:
        logger.exception("Request failed")
        raise HTTPException(
            status_code=500, detail="Couldn't generate download link"
        )
    return RedirectResponse(url=url, status_code=307)







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
        except Exception:
            raise HTTPException(
                status_code=410,
                detail="Couldn't fetch template from storage",
            )

    scan = scan_docx_for_tokens(docx_bytes)
    scan["is_template"] = bool(scan.get("found") or scan.get("unknown"))
    return scan







_FIELD_HELP = {
    "translator": "Your name (Settings)",
    "date": "Today, written in the certification language",
    "source_language": "The project's source language",
    "target_language": "The project's target language",
    "document": "The document title found in the translation",
    "pages": "Source page count",
    "client": "The batch (client) name",
    "translator_email": "Your email",
    "company": "Your team or company name",
    "company_address": "Company address (Settings)",
    "certificate_number": "CERT-year-code, one per project",
    "file_name": "The uploaded file name",
}


@router.get("/template-fields")
def template_fields():
    from app.services.cert_fields import ALIASES, LABELS
    from app.services.cert_template_service import SUPPORTED_FIELDS

    return {
        "fields": [
            {"field": f, "label": LABELS[f], "names": list(ALIASES[f][:4]), "description": _FIELD_HELP[f]}
            for f in LABELS
        ],
        "tokens": [{"name": name, "description": desc} for name, desc in SUPPORTED_FIELDS],
    }


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
        pass
    # Files live in object storage; the local path only exists on old installs.
    from app.services.s3_service import delete_objects_from_s3

    delete_objects_from_s3([file_path])

    return {"status": "deleted"}
