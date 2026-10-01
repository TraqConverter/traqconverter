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
PROTECTED_EXPIRY_DAYS = 30
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


def is_locked(link: DeliveryLink) -> bool:
    return bool(link.protected) and link.unlocked_at is None


def payment_status(link: DeliveryLink) -> Optional[str]:
    if not link.protected:
        return None
    if link.paid_at is not None:
        return "paid"
    if link.unlocked_at is not None:
        return "unlocked"
    return "claimed" if link.paid_claimed_at is not None else "awaiting"


def create(
    db: Session,
    project,
    user,
    kind: str,
    days: int,
    *,
    protected: bool = False,
    amount_cents: Optional[int] = None,
    currency: str = "EUR",
) -> tuple[DeliveryLink, str]:
    """Renders the file now, so later edits don't change what the client gets. Returns (link, token)."""
    data = render(db, project, user, kind)
    name = _file_name(project, kind)
    preview_pages = original_pages = None
    if protected:
        from app.services.protected_preview import split_pages

        preview_pages, original_pages = split_pages(data)
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
        protected=protected,
        amount_cents=amount_cents if protected else None,
        currency=currency,
        preview_pages=preview_pages,
        original_pages=original_pages,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link, token


def revoke(db: Session, link: DeliveryLink) -> None:
    from app.services import s3_service

    if link.revoked_at is None:
        link.revoked_at = datetime.utcnow()
    keys = [link.file_key, *(link.preview_keys or [])]
    link.file_key = None
    link.preview_keys = None
    db.commit()
    if any(keys):
        s3_service.delete_objects_from_s3(keys)


def unlock(db: Session, link: DeliveryLink, user) -> None:
    """The client paid: the link serves the clean file from now on, and the preview images go."""
    from app.services import protected_preview

    if link.unlocked_at is None:
        link.unlocked_at = datetime.utcnow()
        link.unlocked_by = user.id
        db.commit()
    protected_preview.delete(db, link)


def mark_paid(db: Session, link: DeliveryLink, payment_intent: Optional[str]) -> bool:
    """Stripe confirmed the payment: unlock the link. True only for the call that recorded it."""
    from sqlalchemy import func

    from app.services import protected_preview

    now = datetime.utcnow()
    updated = (
        db.query(DeliveryLink)
        .filter(DeliveryLink.id == link.id, DeliveryLink.paid_at.is_(None))
        .update(
            {
                DeliveryLink.paid_at: now,
                DeliveryLink.stripe_payment_intent: payment_intent,
                DeliveryLink.unlocked_at: func.coalesce(DeliveryLink.unlocked_at, now),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    db.refresh(link)
    protected_preview.delete(db, link)
    return updated == 1


def notification_recipient(db: Session, link: DeliveryLink):
    """Who hears about a link's payment: the translator who made it, or the team owner if they've left."""
    from app.models.project import TranslationProject
    from app.models.team import Team
    from app.models.user import User

    recipient = db.query(User).filter(User.id == link.created_by).first() if link.created_by else None
    if recipient is None:
        recipient = (
            db.query(User)
            .join(Team, Team.owner_id == User.id)
            .join(TranslationProject, TranslationProject.team_id == Team.id)
            .filter(TranslationProject.id == link.project_id)
            .first()
        )
    return recipient


def claim_paid(db: Session, link: DeliveryLink) -> bool:
    """Record the client's "I've paid" once. True only for the request that recorded it."""
    updated = (
        db.query(DeliveryLink)
        .filter(DeliveryLink.id == link.id, DeliveryLink.paid_claimed_at.is_(None))
        .update({DeliveryLink.paid_claimed_at: datetime.utcnow()}, synchronize_session=False)
    )
    db.commit()
    db.refresh(link)
    return updated == 1


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
        keys = [k for r in rows for k in (r.file_key, *(r.preview_keys or []))]
        for r in rows:
            r.file_key = None
            r.preview_keys = None
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
