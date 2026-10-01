"""Links the translator sends a client, and the public endpoints behind them."""
import html
import logging
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.dependencies.rate_limit import rate_limit, user_rate_limit
from app.dependencies.tenant import get_user_project_or_404
from app.models.delivery_link import DeliveryLink
from app.models.project import ProjectStatus, TranslationProject
from app.models.team import Team
from app.models.user import User
from app.services import delivery_links, paypal, protected_preview, s3_service, stripe_connect
from app.services.learning import capture_template_in_background

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Delivery links"])
public_router = APIRouter(prefix="/public/delivery", tags=["Delivery links"])

_PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _serialize(link: DeliveryLink) -> dict:
    return {
        "id": str(link.id),
        "kind": link.kind,
        "file_name": link.file_name,
        "token_prefix": link.token_prefix,
        "status": delivery_links.status(link),
        "expires_at": _iso(link.expires_at),
        "created_at": _iso(link.created_at),
        "revoked_at": _iso(link.revoked_at),
        "download_count": link.download_count or 0,
        "last_downloaded_at": _iso(link.last_downloaded_at),
        "protected": bool(link.protected),
        "amount": _amount(link),
        "currency": link.currency or "EUR",
        "payment_status": delivery_links.payment_status(link),
        "paid_claimed_at": _iso(link.paid_claimed_at),
        "unlocked_at": _iso(link.unlocked_at),
        "paid_at": _iso(link.paid_at),
    }


def _amount(link: DeliveryLink) -> Optional[float]:
    return link.amount_cents / 100 if link.amount_cents is not None else None


class _CreatePayload(BaseModel):
    kind: Literal["delivery_pdf", "docx", "pdf"] = "delivery_pdf"
    # Default: 7 days, or 30 for a protected link.
    expires_in_days: Optional[Literal[1, 7, 30]] = None
    protected: bool = False
    amount: Optional[Decimal] = None
    currency: Literal["EUR", "GBP", "USD"] = "EUR"


def _protected_amount(db: Session, project: TranslationProject, data: _CreatePayload) -> int:
    """The amount in cents for a protected link, or 422."""
    if data.amount is None:
        raise HTTPException(status_code=422, detail="Enter the amount the client should pay")
    try:
        cents = paypal.to_cents(data.amount)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    team = db.query(Team).filter(Team.id == project.team_id).first()
    if not team or not (team.paypal_me or stripe_connect.is_active(team)):
        raise HTTPException(
            status_code=422, detail="Connect Stripe or add your PayPal.me name in Settings → Payments first"
        )
    return cents


@router.post(
    "/{project_id}/delivery-links",
    dependencies=[
        Depends(require_feature("download_translation")),
        Depends(user_rate_limit("delivery_link_create", 30, 3600)),
    ],
)
def create_delivery_link(
    project_id: UUID,
    data: _CreatePayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.delivery_pdf import DeliveryError

    project = get_user_project_or_404(db, project_id, current_user)
    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="The translation must finish before it can be shared.")
    cents = _protected_amount(db, project, data) if data.protected else None
    # The preview is rendered from the delivery PDF, so that's what a protected link always holds.
    kind = "delivery_pdf" if data.protected else data.kind
    days = data.expires_in_days or (delivery_links.PROTECTED_EXPIRY_DAYS if data.protected else 7)
    try:
        link, token = delivery_links.create(
            db,
            project,
            current_user,
            kind,
            days,
            protected=data.protected,
            amount_cents=cents,
            currency=data.currency,
        )
    except DeliveryError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Delivery link creation failed (project=%s)", project.id)
        raise HTTPException(status_code=500, detail="Couldn't prepare the file for the link")

    background_tasks.add_task(capture_template_in_background, project.id, current_user.id)
    # The only time the full link is returned; just its hash is stored.
    return {**_serialize(link), "url": delivery_links.link_url(token)}


@router.get("/{project_id}/delivery-links")
def list_delivery_links(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    links = (
        db.query(DeliveryLink)
        .filter(DeliveryLink.project_id == project.id)
        .order_by(DeliveryLink.created_at.desc())
        .limit(100)
        .all()
    )
    return [_serialize(link) for link in links]


@router.delete("/{project_id}/delivery-links/{link_id}")
def revoke_delivery_link(
    project_id: UUID,
    link_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    link = (
        db.query(DeliveryLink)
        .filter(DeliveryLink.id == link_id, DeliveryLink.project_id == project.id)
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    delivery_links.revoke(db, link)
    return _serialize(link)


@router.post("/{project_id}/delivery-links/{link_id}/unlock")
def unlock_delivery_link(
    project_id: UUID,
    link_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    link = (
        db.query(DeliveryLink)
        .filter(DeliveryLink.id == link_id, DeliveryLink.project_id == project.id)
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    if not link.protected:
        raise HTTPException(status_code=400, detail="This link isn't protected.")
    if link.revoked_at is not None:
        raise HTTPException(status_code=400, detail="This link was revoked.")
    delivery_links.unlock(db, link, current_user)
    return _serialize(link)


def _link_team(db: Session, link: DeliveryLink) -> Optional[Team]:
    return (
        db.query(Team)
        .join(TranslationProject, TranslationProject.team_id == Team.id)
        .filter(TranslationProject.id == link.project_id)
        .first()
    )


def _company(db: Session, link: DeliveryLink) -> str:
    team = _link_team(db, link)
    return (team.name if team else "") or ""


def _usable_link(db: Session, token: str) -> DeliveryLink:
    link = delivery_links.find(db, token)
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found", headers=_PUBLIC_HEADERS)
    state = delivery_links.status(link)
    if state != "active":
        detail = "The sender withdrew this link." if state == "revoked" else "This link has expired."
        raise HTTPException(status_code=410, detail=detail, headers=_PUBLIC_HEADERS)
    return link


@public_router.get("/{token}", dependencies=[Depends(rate_limit("public_delivery", 60, 60))])
def public_delivery_info(token: str, db: Session = Depends(get_db)):
    link = delivery_links.find(db, token)
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found", headers=_PUBLIC_HEADERS)
    state = delivery_links.status(link)
    body = {"valid": state == "active", "status": state, "company": _company(db, link)}
    if state != "active":
        body["detail"] = "The sender withdrew this link." if state == "revoked" else "This link has expired."
        return JSONResponse(status_code=410, content=body, headers=_PUBLIC_HEADERS)
    body.update(
        file_name=link.file_name,
        kind=link.kind,
        file_size=link.file_size,
        expires_at=_iso(link.expires_at),
        protected=bool(link.protected),
        locked=delivery_links.is_locked(link),
    )
    if link.protected:
        body.update(
            amount=_amount(link),
            currency=link.currency or "EUR",
            paid_claimed=link.paid_claimed_at is not None,
        )
        if body["locked"]:
            team = _link_team(db, link)
            handle = team.paypal_me if team else None
            body.update(
                preview_pages=link.preview_pages or 0,
                original_pages=link.original_pages or 0,
                card_payment=bool(link.amount_cents) and stripe_connect.is_active(team),
                paypal_url=paypal.payment_url(handle, link.amount_cents, link.currency or "EUR")
                if handle and link.amount_cents
                else None,
            )
    return JSONResponse(content=body, headers=_PUBLIC_HEADERS)


@public_router.post("/{token}/checkout", dependencies=[Depends(rate_limit("public_delivery_checkout", 10, 600))])
def public_delivery_checkout(token: str, db: Session = Depends(get_db)):
    """A Stripe Checkout page for the link's amount, charged on the translator's own Stripe account."""
    link = delivery_links.find(db, token)
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found", headers=_PUBLIC_HEADERS)
    team = _link_team(db, link)
    if (
        delivery_links.status(link) != "active"
        or not delivery_links.is_locked(link)
        or not link.amount_cents
        or not stripe_connect.is_active(team)
    ):
        raise HTTPException(status_code=409, detail="This link can't be paid online.", headers=_PUBLIC_HEADERS)
    try:
        url = stripe_connect.checkout_url(link, team, token)
    except Exception:
        logger.exception("Stripe checkout failed (link=%s)", link.id)
        raise HTTPException(status_code=502, detail="Payment isn't available right now.", headers=_PUBLIC_HEADERS)
    return JSONResponse(content={"checkout_url": url}, headers=_PUBLIC_HEADERS)


@public_router.get("/{token}/file", dependencies=[Depends(rate_limit("public_delivery_file", 20, 60))])
def public_delivery_file(token: str, db: Session = Depends(get_db)):
    link = _usable_link(db, token)
    # The actual protection: until the translator unlocks the link, the file isn't served.
    if delivery_links.is_locked(link):
        raise HTTPException(
            status_code=403, detail="This document is available once payment is confirmed.", headers=_PUBLIC_HEADERS
        )
    try:
        chunks = s3_service.stream_object(link.file_key)
    except Exception:
        logger.exception("Delivery file missing from storage (link=%s)", link.id)
        raise HTTPException(status_code=502, detail="The file isn't available right now.", headers=_PUBLIC_HEADERS)
    delivery_links.record_download(db, link)
    headers = {**_PUBLIC_HEADERS, "Content-Disposition": s3_service._attachment(link.file_name)}
    if link.file_size:
        headers["Content-Length"] = str(link.file_size)
    return StreamingResponse(
        chunks,
        media_type=delivery_links.MEDIA_TYPES.get(link.kind, "application/octet-stream"),
        headers=headers,
    )


@public_router.get(
    "/{token}/preview/{page}", dependencies=[Depends(rate_limit("public_delivery_preview", 120, 60))]
)
def public_delivery_preview(token: str, page: int, db: Session = Depends(get_db)):
    link = _usable_link(db, token)
    if not delivery_links.is_locked(link) or page < 1 or page > (link.preview_pages or 0):
        raise HTTPException(status_code=404, detail="Page not found", headers=_PUBLIC_HEADERS)
    try:
        keys = protected_preview.ensure(db, link)
        data = b"".join(s3_service.stream_object(keys[page - 1]))
    except IndexError:
        raise HTTPException(status_code=404, detail="Page not found", headers=_PUBLIC_HEADERS)
    except Exception:
        logger.exception("Preview unavailable (link=%s)", link.id)
        raise HTTPException(status_code=502, detail="The preview isn't available right now.", headers=_PUBLIC_HEADERS)
    return Response(content=data, media_type="image/png", headers=_PUBLIC_HEADERS)


@public_router.post("/{token}/paid", dependencies=[Depends(rate_limit("public_delivery_paid", 5, 3600))])
def public_delivery_paid(token: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    link = _usable_link(db, token)
    if not link.protected:
        raise HTTPException(status_code=404, detail="Link not found", headers=_PUBLIC_HEADERS)
    if delivery_links.is_locked(link) and delivery_links.claim_paid(db, link):
        background_tasks.add_task(_notify_paid, link.id)
    return JSONResponse(
        content={"paid_claimed": link.paid_claimed_at is not None, "locked": delivery_links.is_locked(link)},
        headers=_PUBLIC_HEADERS,
    )


def _notify_paid(link_id) -> None:
    """Email the translator who made the link (the team owner if they've left): the client says they paid."""
    from app.config import settings
    from app.database import SessionLocal
    from app.services import email_service

    db = SessionLocal()
    try:
        link = db.query(DeliveryLink).filter(DeliveryLink.id == link_id).first()
        if link is None:
            return
        recipient = delivery_links.notification_recipient(db, link)
        if recipient is None or not recipient.email:
            return
        amount = paypal.display_amount(link.amount_cents or 0, link.currency or "EUR")
        message = (
            f"Your client says they've paid {amount} for {link.file_name}. "
            "Check PayPal, then unlock it in the editor (Share with client)."
        )
        editor = f"{settings.FRONTEND_URL.rstrip('/')}/editor/{link.project_id}"
        email_service.send_email(
            to=recipient.email,
            subject=f"Your client says they've paid {amount}",
            html=f'<p>{html.escape(message)}</p><p><a href="{html.escape(editor)}">Open the project</a></p>',
            text_fallback=f"{message}\n\n{editor}",
        )
    except Exception:
        logger.exception("Couldn't send the payment-claim email (link=%s)", link_id)
    finally:
        db.close()


def notify_stripe_paid(link_id) -> None:
    """Email the translator who made the link (the team owner if they've left): Stripe confirmed the payment."""
    from app.config import settings
    from app.database import SessionLocal
    from app.services import email_service

    db = SessionLocal()
    try:
        link = db.query(DeliveryLink).filter(DeliveryLink.id == link_id).first()
        if link is None:
            return
        recipient = delivery_links.notification_recipient(db, link)
        if recipient is None or not recipient.email:
            return
        amount = paypal.display_amount(link.amount_cents or 0, link.currency or "EUR")
        message = f"Your client paid {amount} for {link.file_name}. The document is now unlocked for them."
        editor = f"{settings.FRONTEND_URL.rstrip('/')}/editor/{link.project_id}"
        email_service.send_email(
            to=recipient.email,
            subject=f"Your client paid {amount}",
            html=f'<p>{html.escape(message)}</p><p><a href="{html.escape(editor)}">Open the project</a></p>',
            text_fallback=f"{message}\n\n{editor}",
        )
    except Exception:
        logger.exception("Couldn't send the payment email (link=%s)", link_id)
    finally:
        db.close()
