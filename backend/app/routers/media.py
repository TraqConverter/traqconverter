"""The team's media library: stamps, logos and signatures, each optionally used automatically for a target language."""
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.file_validation import local_file_name
from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.dependencies.rate_limit import user_rate_limit
from app.dependencies.tenant import can_manage_team
from app.models.media_asset import AUTO_KINDS, NAME_MAX, MediaAsset
from app.models.user import User
from app.routers.settings import _resolve_team
from app.services import docx_images, media_library
from app.services.docx_blocks import DocxEditError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["Media"], dependencies=[Depends(require_feature("media"))])

Kind = Literal["stamp", "logo", "signature", "other"]
_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
_upload_limit = [Depends(user_rate_limit("media_upload", max_requests=60, per_seconds=3600))]


def asset_json(asset: MediaAsset) -> dict:
    from app.services.s3_service import generate_presigned_download_url

    try:
        url = generate_presigned_download_url(asset.s3_key, inline=True)
    except Exception:
        logger.warning("Couldn't sign the preview of media asset %s", asset.id)
        url = None
    return {
        "id": str(asset.id),
        "name": asset.name,
        "kind": asset.kind,
        "language": asset.language,
        "auto_use": bool(asset.auto_use),
        "mime_type": asset.mime_type,
        "width_px": asset.width_px,
        "height_px": asset.height_px,
        "size_bytes": asset.size_bytes,
        "created_at": asset.created_at.isoformat() + "Z" if asset.created_at else None,
        "url": url,
    }


def _language(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    code = media_library.language_base(value)
    if code is None:
        raise HTTPException(status_code=422, detail="language must be a language code such as en, it or pt-BR")
    return code


def _name(value: str) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise HTTPException(status_code=422, detail="Give the picture a name")
    if len(name) > NAME_MAX:
        raise HTTPException(status_code=422, detail=f"Names are {NAME_MAX} characters or fewer")
    return name


def _editable_team(db: Session, user: User):
    team = _resolve_team(db, user)
    if not can_manage_team(db, team, user):
        raise HTTPException(status_code=403, detail="Only the team owner or an admin can change the media library")
    return team


def _own_asset(db: Session, team, asset_id: UUID) -> MediaAsset:
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id, MediaAsset.team_id == team.id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Picture not found")
    return asset


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        # Two saves racing to be the automatic pick for one language.
        db.rollback()
        raise HTTPException(status_code=409, detail="Another picture was just made automatic for that language; reload and try again")


@router.get("")
def list_media(
    kind: Optional[Kind] = None,
    language: Optional[str] = Query(None, max_length=20),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    team = _resolve_team(db, user)
    assets = media_library.team_assets(db, team.id, kind, _language(language))
    return {"assets": [asset_json(a) for a in assets], "can_edit": can_manage_team(db, team, user)}


@router.post("", dependencies=_upload_limit)
async def upload_media(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None, max_length=200),
    kind: Kind = Form("other"),
    language: Optional[str] = Form(None, max_length=20),
    auto_use: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.s3_service import upload_file_to_s3

    team = _editable_team(db, user)
    filename = local_file_name(file.filename or "picture.png")
    if Path(filename).suffix.lower() not in _EXTENSIONS:
        raise HTTPException(status_code=400, detail="Use a PNG, JPG or WebP image")
    raw = await file.read(docx_images.MAX_UPLOAD_BYTES + 1)
    try:
        prepared = docx_images.prepare_image(raw)
    except DocxEditError as e:
        raise HTTPException(status_code=400, detail=str(e))
    lang = _language(language)
    label = _name(name if name is not None and name.strip() else Path(filename).stem.replace("_", " ")[:NAME_MAX])
    if auto_use and kind not in AUTO_KINDS:
        raise HTTPException(status_code=422, detail="Only stamps and logos can be used automatically")

    tmp_dir = Path(tempfile.mkdtemp(prefix="media_"))
    try:
        path = tmp_dir / f"{Path(filename).stem[:60] or 'picture'}.{'jpg' if prepared.ext == 'jpeg' else prepared.ext}"
        path.write_bytes(prepared.data)
        key = upload_file_to_s3(path, prefix="media")
    except Exception:
        logger.exception("Media upload failed (team=%s)", team.id)
        raise HTTPException(status_code=502, detail="Couldn't save the picture. Try again in a minute.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    asset = MediaAsset(
        team_id=team.id,
        uploaded_by=user.id,
        name=label,
        kind=kind,
        language=lang,
        s3_key=key,
        mime_type="image/png" if prepared.ext == "png" else "image/jpeg",
        width_px=prepared.width_px,
        height_px=prepared.height_px,
        size_bytes=len(prepared.data),
        auto_use=False,
    )
    db.add(asset)
    db.flush()
    if auto_use:
        media_library.set_auto_use(db, asset)
    _commit(db)
    db.refresh(asset)
    return asset_json(asset)


class _Update(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    kind: Optional[Kind] = None
    language: Optional[str] = Field(default=None, max_length=20)
    auto_use: Optional[bool] = None


@router.patch("/{asset_id}")
def update_media(
    asset_id: UUID,
    payload: _Update,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """A `language` of null makes the picture language-free; leaving the field out keeps it."""
    team = _editable_team(db, user)
    asset = _own_asset(db, team, asset_id)
    sent = payload.model_fields_set
    if payload.name is not None:
        asset.name = _name(payload.name)
    if payload.kind is not None:
        asset.kind = payload.kind
    if "language" in sent:
        asset.language = _language(payload.language)
    wants_auto = payload.auto_use if payload.auto_use is not None else bool(asset.auto_use)
    if wants_auto and asset.kind not in AUTO_KINDS:
        if payload.auto_use:
            raise HTTPException(status_code=422, detail="Only stamps and logos can be used automatically")
        wants_auto = False
    # Clear first: a kind or language change may land on another picture's automatic slot.
    asset.auto_use = False
    db.flush()
    if wants_auto:
        media_library.set_auto_use(db, asset)
    _commit(db)
    db.refresh(asset)
    return asset_json(asset)


@router.delete("/{asset_id}")
def delete_media(
    asset_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Documents that already show the picture keep their own embedded copy."""
    from app.services.s3_service import delete_objects_from_s3

    team = _editable_team(db, user)
    asset = _own_asset(db, team, asset_id)
    key = asset.s3_key
    db.delete(asset)
    media_library.forget_legacy_key(db, team.id, key)
    db.commit()
    still_used = db.query(MediaAsset.id).filter(MediaAsset.s3_key == key).first() is not None
    if not still_used:
        delete_objects_from_s3([key])
    return {"deleted": str(asset_id)}
