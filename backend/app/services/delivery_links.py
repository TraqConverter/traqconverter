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


def _fernet():
    import base64

    from cryptography.fernet import Fernet

    from app.config import settings

    key = hashlib.sha256(b"delivery-link-token:" + settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def team_url(link: DeliveryLink) -> Optional[str]:
    """The link's full URL for the team to copy again; None for links made before tokens were kept, or revoked ones."""
    if not link.token_sealed or link.revoked_at is not None:
        return None
    from cryptography.fernet import InvalidToken

    try:
        return link_url(_fernet().decrypt(link.token_sealed.encode()).decode())
    except InvalidToken:
        logger.warning("Delivery link token can't be decrypted (link=%s)", link.id)
        return None


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


# The Jobs page payment filter: "paid" covers both a card payment and a manual mark-as-paid.
PROJECT_PAYMENT_FILTERS = ("claimed", "awaiting", "paid")


def _project_payment_state():
    from sqlalchemy import case

    return case(
        (DeliveryLink.paid_at.isnot(None), "paid_card"),
        (DeliveryLink.unlocked_at.isnot(None), "marked_paid"),
        (DeliveryLink.paid_claimed_at.isnot(None), "claimed"),
        else_="awaiting",
    )


def _deciding_links(db: Session, now: Optional[datetime] = None):
    """Per project, the protected link its payment status comes from: the latest unlocked one, else the newest active one."""
    from sqlalchemy import and_, or_

    now = now or datetime.utcnow()
    return (
        db.query(DeliveryLink)
        .filter(
            DeliveryLink.protected.is_(True),
            DeliveryLink.revoked_at.is_(None),
            or_(
                DeliveryLink.unlocked_at.isnot(None),
                and_(DeliveryLink.expires_at > now, DeliveryLink.file_key.isnot(None)),
            ),
        )
        .distinct(DeliveryLink.project_id)
        .order_by(DeliveryLink.project_id, DeliveryLink.unlocked_at.desc().nullslast(), DeliveryLink.created_at.desc())
    )


def deciding_links_for(db: Session, project_ids: list) -> dict:
    """{project_id: link} in one query, for the projects that have a link deciding their payment status."""
    if not project_ids:
        return {}
    links = _deciding_links(db).filter(DeliveryLink.project_id.in_(project_ids)).all()
    return {link.project_id: link for link in links}


def project_payment_states(db: Session):
    """Subquery of (project_id, state) with state one of paid_card, marked_paid, claimed, awaiting."""
    return (
        _deciding_links(db)
        .with_entities(DeliveryLink.project_id.label("project_id"), _project_payment_state().label("state"))
        .subquery()
    )


def project_payment_filter(db: Session, wanted: str):
    """SQL condition on TranslationProject for one of PROJECT_PAYMENT_FILTERS."""
    from sqlalchemy import select

    from app.models.project import TranslationProject

    states = project_payment_states(db)
    values = ("paid_card", "marked_paid") if wanted == "paid" else (wanted,)
    return TranslationProject.id.in_(select(states.c.project_id).where(states.c.state.in_(values)))


def member_name(user) -> Optional[str]:
    if user is None:
        return None
    return (user.full_name or "").strip() or (user.email or "").split("@")[0] or None


def project_payment(link: DeliveryLink, marked_by, can_mark_paid: bool) -> dict:
    """The Jobs badge for a project. Team member names only; nothing about the client is stored or shown."""
    state = payment_status(link)
    state = {"paid": "paid_card", "unlocked": "marked_paid"}.get(state, state)
    return {
        "state": state,
        "link_id": str(link.id),
        "amount": link.amount_cents / 100 if link.amount_cents is not None else None,
        "currency": link.currency or "EUR",
        "sent_at": _iso(link.created_at),
        "expires_at": _iso(link.expires_at),
        "claimed_at": _iso(link.paid_claimed_at),
        "paid_at": _iso(link.paid_at),
        "unlocked_at": _iso(link.unlocked_at),
        "marked_by": member_name(marked_by) if state == "marked_paid" else None,
        "can_mark_paid": can_mark_paid and state in ("claimed", "awaiting"),
    }


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


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
        token_sealed=seal_token(token),
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


def record_download(db: Session, link: DeliveryLink) -> bool:
    """Count a download; True only for the link's first one."""
    from sqlalchemy import func, update

    count = db.execute(
        update(DeliveryLink)
        .where(DeliveryLink.id == link.id)
        .values(
            download_count=func.coalesce(DeliveryLink.download_count, 0) + 1,
            last_downloaded_at=datetime.utcnow(),
        )
        .returning(DeliveryLink.download_count)
    ).scalar()
    first = count == 1
    if first:
        notify_creator(db, link, "client_downloaded")
    db.commit()
    db.refresh(link)
    return first


_CREATOR_TEXT = {
    "client_paid": ("Your client paid {amount} for {file} — unlocked", "Paid by card; the clean file is theirs now"),
    "client_claimed_paid": (
        "Your client says they've paid {amount} for {file}",
        "Check that the money has arrived, then mark it as paid on Projects or in Share with client",
    ),
    "client_downloaded": ("Your client downloaded {file}", "First download of the link you shared"),
}


def notify_creator(db: Session, link: DeliveryLink, kind: str) -> None:
    """In-app notice to the link's creator (team owner if they've left). File name and amount only, no client details."""
    from app.models.project import TranslationProject
    from app.services import notifications, paypal

    try:
        recipient = notification_recipient(db, link)
        if recipient is None:
            return
        title, body = _CREATOR_TEXT[kind]
        amount = paypal.display_amount(link.amount_cents or 0, link.currency or "EUR")
        team_id = db.query(TranslationProject.team_id).filter(TranslationProject.id == link.project_id).scalar()
        notifications.notify(
            db, recipient.id, kind,
            title.format(amount=amount, file=link.file_name), body,
            link=notifications.editor_link(link.project_id), project_id=link.project_id, team_id=team_id,
        )
    except Exception:
        logger.exception("Couldn't notify the creator of link %s (%s)", link.id, kind)


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
