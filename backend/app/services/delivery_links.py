"""Client download links: a random token (only its hash is stored) to a snapshot of an export kept in storage."""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.delivery_link import DeliveryLink

logger = logging.getLogger(__name__)

TOKEN_BYTES = 32
PREFIX_LEN = 6
KINDS = ("delivery_pdf", "docx", "pdf")
EXPIRY_DAYS = (1, 7, 30)
# Snapshots stay in storage this long after the link expires, then are deleted.
FILE_RETENTION = timedelta(days=7)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,128}$")

MEDIA_TYPES = {
    "delivery_pdf": "application/pdf",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def link_url(token: str) -> str:
    from app.config import settings

    return f"{settings.FRONTEND_URL.rstrip('/')}/d/{token}"


def find(db: Session, token: str) -> Optional[DeliveryLink]:
    if not _TOKEN_RE.match(token or ""):
        return None
    digest = hash_token(token)
    link = db.query(DeliveryLink).filter(DeliveryLink.token_hash == digest).first()
    if link is None or not hmac.compare_digest(link.token_hash, digest):
        return None
    return link


def status(link: DeliveryLink, now: Optional[datetime] = None) -> str:
    if link.revoked_at is not None:
        return "revoked"
    if link.expires_at <= (now or datetime.utcnow()) or not link.file_key:
        return "expired"
    return "active"


def _file_name(project, kind: str) -> str:
    from app.services.delivery_pdf import delivery_filename

    name = delivery_filename(project)
    return name[: -len(".pdf")] + ".docx" if kind == "docx" else name


def render(db: Session, project, user, kind: str) -> bytes:
    if kind == "delivery_pdf":
        from app.services.delivery_pdf import build_delivery_pdf

        return build_delivery_pdf(db, project, user)
    from app.routers.export import render_export

    return render_export(db, project, user, kind).getvalue()


def _store(data: bytes, name: str) -> str:
    from app.services import s3_service

    tmp = Path(tempfile.mkdtemp(prefix="delivery_"))
    try:
        path = tmp / re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        path.write_bytes(data)
        return s3_service.upload_file_to_s3(path, prefix="delivery")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def create(db: Session, project, user, kind: str, days: int) -> tuple[DeliveryLink, str]:
    """Renders the file now, so later edits don't change what the client gets. Returns (link, token)."""
    data = render(db, project, user, kind)
    name = _file_name(project, kind)
    key = _store(data, name)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    link = DeliveryLink(
        project_id=project.id,
        token_hash=hash_token(token),
        token_prefix=token[:PREFIX_LEN],
        kind=kind,
        file_name=name,
        file_key=key,
        file_size=len(data),
        expires_at=datetime.utcnow() + timedelta(days=days),
        created_by=user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link, token


def revoke(db: Session, link: DeliveryLink) -> None:
    from app.services import s3_service

    if link.revoked_at is None:
        link.revoked_at = datetime.utcnow()
    key, link.file_key = link.file_key, None
    db.commit()
    if key:
        s3_service.delete_objects_from_s3([key])


def record_download(db: Session, link: DeliveryLink) -> None:
    link.download_count = (link.download_count or 0) + 1
    link.last_downloaded_at = datetime.utcnow()
    db.commit()


def purge_expired_files(now: Optional[datetime] = None) -> int:
    """Delete the snapshots of links that expired more than FILE_RETENTION ago; the rows stay for the history."""
    from app.database import SessionLocal
    from app.services import s3_service

    cutoff = (now or datetime.utcnow()) - FILE_RETENTION
    db = SessionLocal()
    try:
        rows = (
            db.query(DeliveryLink)
            .filter(DeliveryLink.file_key.isnot(None), DeliveryLink.expires_at <= cutoff)
            .limit(200)
            .all()
        )
        keys = [r.file_key for r in rows]
        for r in rows:
            r.file_key = None
        db.commit()
        if keys:
            s3_service.delete_objects_from_s3(keys)
        return len(rows)
    except Exception:
        db.rollback()
        logger.exception("Couldn't purge expired delivery files")
        return 0
    finally:
        db.close()
