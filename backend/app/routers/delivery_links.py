"""Links the translator sends a client, and the public endpoints behind them."""
import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
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
from app.services import delivery_links, s3_service
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
    }


class _CreatePayload(BaseModel):
    kind: Literal["delivery_pdf", "docx", "pdf"] = "delivery_pdf"
    expires_in_days: Literal[1, 7, 30] = 7


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
    try:
        link, token = delivery_links.create(db, project, current_user, data.kind, data.expires_in_days)
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


def _company(db: Session, link: DeliveryLink) -> str:
    row = (
        db.query(Team.name)
        .join(TranslationProject, TranslationProject.team_id == Team.id)
        .filter(TranslationProject.id == link.project_id)
        .first()
    )
    return (row[0] if row else "") or ""


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
    )
    return JSONResponse(content=body, headers=_PUBLIC_HEADERS)


@public_router.get("/{token}/file", dependencies=[Depends(rate_limit("public_delivery_file", 20, 60))])
def public_delivery_file(token: str, db: Session = Depends(get_db)):
    link = _usable_link(db, token)
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
