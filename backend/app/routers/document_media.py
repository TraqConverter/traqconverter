"""Pictures, stamps and the certification page inside the editable translated document."""
import logging
from datetime import date
from pathlib import Path
from typing import Literal, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.dependencies.rate_limit import user_rate_limit
from app.dependencies.tenant import get_user_project_or_404
from app.models.certification import Certification
from app.models.document_version import DocumentVersion
from app.models.project import TranslationProject, is_dtp
from app.models.user import User
from app.routers.document import _initial_builder, _locked_project, _require_version
from app.services import cert_locale, cert_page, docx_certification, docx_images, document_editor
from app.services.docx_blocks import DocxEditError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Document"])

BLOCK_ID = r"^_b[0-9a-f]{8}$"
IMAGE_ID = r"^img_[0-9a-f]{8}$"
Position = Literal["before", "after", "inline"]
Align = Literal["left", "center", "right"]
_cert_feature = [Depends(require_feature("certifications"))]
_upload_limit = [Depends(user_rate_limit("doc_images", max_requests=120, per_seconds=3600))]


class _ImagePlacement(BaseModel):
    version: int
    block_id: str = Field(pattern=BLOCK_ID)
    position: Position = "after"
    width_cm: Optional[float] = Field(default=None, ge=0.5, le=19)
    align: Optional[Align] = None


class _Move(BaseModel):
    version: int
    target_block_id: str = Field(pattern=BLOCK_ID)
    position: Position = "after"
    align: Optional[Align] = None


class _Float(BaseModel):
    version: int
    target_block_id: str = Field(pattern=BLOCK_ID)
    x_emu: int = Field(ge=-21_600_000, le=21_600_000)
    y_emu: int = Field(ge=-21_600_000, le=21_600_000)


class _Resize(BaseModel):
    version: int
    width_cm: float = Field(ge=0.5, le=19)


class _Align(BaseModel):
    version: int
    align: Align


# A team template's id, "standard" for the built-in page, or left out for the project's saved pick.
TemplateChoice = Optional[Union[UUID, Literal["standard"]]]


class _CertCreate(BaseModel):
    version: int
    template_id: TemplateChoice = None


class _CertFields(BaseModel):
    translator: Optional[str] = Field(default=None, max_length=200)
    date: Optional[str] = Field(default=None, max_length=100)
    source_language: Optional[str] = Field(default=None, max_length=100)
    target_language: Optional[str] = Field(default=None, max_length=100)
    document: Optional[str] = Field(default=None, max_length=300)
    pages: Optional[str] = Field(default=None, max_length=20)
    client: Optional[str] = Field(default=None, max_length=200)
    translator_email: Optional[str] = Field(default=None, max_length=200)
    company: Optional[str] = Field(default=None, max_length=200)
    company_address: Optional[str] = Field(default=None, max_length=300)
    certificate_number: Optional[str] = Field(default=None, max_length=100)
    file_name: Optional[str] = Field(default=None, max_length=300)


class _CertUpdate(BaseModel):
    version: int
    fields: _CertFields = Field(default_factory=_CertFields)
    template_id: TemplateChoice = None


def _edit(db: Session, project_id: UUID, user: User, version: int, note: str, change):
    """Apply `change(data) -> bytes` to the current document under the row lock and save it as a new version."""
    project = _locked_project(db, project_id, user)
    _require_version(project, version)
    data, _ = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    try:
        new_data = change(data, project)
    except docx_images.ImageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DocxEditError as e:
        raise HTTPException(status_code=409, detail=str(e) or "The document changed; reloaded the latest version")
    if new_data is not data:
        document_editor.save_version(db, project, new_data, note, user)
    db.commit()
    return project.document_version


def _asset_key(db: Session, project: TranslationProject, user: User, asset: str) -> Optional[str]:
    if asset == "logo":
        return getattr(user, "logo_s3_key", None)
    from app.models.team import Team

    team = db.query(Team).filter(Team.id == project.team_id).first()
    return team.stamp_s3_key if team else None


def _load_asset(key: str, remove_background: bool) -> docx_images.PreparedImage:
    try:
        raw = document_editor._download(key)
    except Exception:
        logger.exception("Couldn't load saved asset %s", key)
        raise HTTPException(status_code=502, detail="Couldn't load that image from storage")
    try:
        return docx_images.prepare_image(raw, remove_background=remove_background)
    except DocxEditError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}/document/status")
def document_status(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_user_project_or_404(db, project_id, user)
    data, version = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    row = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.project_id == project.id, DocumentVersion.version == version)
        .first()
    )
    return {
        "version": version,
        "updated_at": row.created_at.isoformat() + "Z" if row and row.created_at else None,
        "certification": docx_certification.has_certification(data),
        "images": len(docx_images.list_images(data)),
        "pages": project.page_count,
    }


@router.get("/{project_id}/document/images")
def list_document_images(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_user_project_or_404(db, project_id, user)
    data, version = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    return {"version": version, "images": docx_images.list_images(data)}


@router.post("/{project_id}/document/images", dependencies=_upload_limit)
async def upload_document_image(
    project_id: UUID,
    file: UploadFile = File(...),
    version: int = Form(...),
    block_id: str = Form(..., pattern=BLOCK_ID),
    position: Position = Form("after"),
    width_cm: Optional[float] = Form(None, ge=0.5, le=19),
    align: Align = Form("left"),
    remove_background: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    get_user_project_or_404(db, project_id, user)
    raw = await file.read(docx_images.MAX_UPLOAD_BYTES + 1)
    if Path(file.filename or "").suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail="Use a PNG, JPG or WebP image")
    try:
        prepared = docx_images.prepare_image(raw, remove_background=remove_background)
    except DocxEditError as e:
        raise HTTPException(status_code=400, detail=str(e))
    inserted = {}

    def change(data, _project):
        out, inserted["id"] = docx_images.insert_image(data, prepared, block_id, position, width_cm, align)
        return out

    new_version = _edit(db, project_id, user, version, "Inserted an image", change)
    return {"version": new_version, "image_id": inserted["id"]}


@router.get("/{project_id}/document/assets")
def list_assets(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.s3_service import generate_presigned_download_url

    project = get_user_project_or_404(db, project_id, user)
    out = {}
    for asset in ("logo", "stamp"):
        key = _asset_key(db, project, user, asset)
        url = None
        if key:
            try:
                url = generate_presigned_download_url(key, inline=True)
            except Exception:
                logger.warning("Couldn't sign %s url", asset)
        out[asset] = {"available": bool(key), "url": url}
    return out


@router.post("/{project_id}/document/assets/{asset}", dependencies=_upload_limit)
def insert_asset(
    project_id: UUID,
    asset: Literal["logo", "stamp"],
    payload: _ImagePlacement,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, user)
    key = _asset_key(db, project, user, asset)
    if not key:
        raise HTTPException(status_code=404, detail=f"No {asset} saved in Settings")
    prepared = _load_asset(key, remove_background=asset == "stamp")
    default_width = docx_certification.STAMP_WIDTH_CM if asset == "stamp" else docx_certification.LOGO_WIDTH_CM
    inserted = {}

    def change(data, _project):
        out, inserted["id"] = docx_images.insert_image(
            data, prepared, payload.block_id, payload.position, payload.width_cm or default_width, payload.align or "left"
        )
        return out

    new_version = _edit(db, project_id, user, payload.version, f"Inserted {asset}", change)
    return {"version": new_version, "image_id": inserted["id"]}


@router.post("/{project_id}/document/images/{image_id}/move")
def move_image(
    project_id: UUID,
    payload: _Move,
    image_id: str = PathParam(pattern=IMAGE_ID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    change = lambda data, _p: docx_images.move_image(data, image_id, payload.target_block_id, payload.position, payload.align)
    return {"version": _edit(db, project_id, user, payload.version, "Moved an image", change)}


@router.post("/{project_id}/document/images/{image_id}/position")
def position_image(
    project_id: UUID,
    payload: _Float,
    image_id: str = PathParam(pattern=IMAGE_ID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    change = lambda data, _p: docx_images.float_image(data, image_id, payload.target_block_id, payload.x_emu, payload.y_emu)
    return {"version": _edit(db, project_id, user, payload.version, "Positioned an image", change)}


@router.post("/{project_id}/document/images/{image_id}/resize")
def resize_image(
    project_id: UUID,
    payload: _Resize,
    image_id: str = PathParam(pattern=IMAGE_ID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    change = lambda data, _p: docx_images.resize_image(data, image_id, payload.width_cm)
    return {"version": _edit(db, project_id, user, payload.version, "Resized an image", change)}


@router.post("/{project_id}/document/images/{image_id}/align")
def align_image(
    project_id: UUID,
    payload: _Align,
    image_id: str = PathParam(pattern=IMAGE_ID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    change = lambda data, _p: docx_images.align_image(data, image_id, payload.align)
    return {"version": _edit(db, project_id, user, payload.version, "Aligned an image", change)}


@router.delete("/{project_id}/document/images/{image_id}")
def delete_image(
    project_id: UUID,
    image_id: str = PathParam(pattern=IMAGE_ID),
    version: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    change = lambda data, _p: docx_images.delete_image(data, image_id)
    return {"version": _edit(db, project_id, user, version, "Deleted an image", change)}


def _page_template(db: Session, project: TranslationProject, template_id) -> tuple[Optional[Certification], Optional[bytes]]:
    try:
        cert = cert_page.page_template_for(db, project, template_id)
    except cert_page.TemplateNotFound:
        raise HTTPException(status_code=404, detail="Certification template not found")
    if cert is None:
        return None, None
    if not cert_page.is_docx(cert):
        raise HTTPException(status_code=422, detail="Only Word (.docx) templates can be placed in the document")
    try:
        return cert, cert_page.load_bytes(cert)
    except Exception:
        logger.exception("Couldn't load certification template %s", cert.id)
        raise HTTPException(status_code=502, detail="Couldn't load the certification template")


def _current_choice(db: Session, project: TranslationProject, data: bytes) -> str:
    """The template the page was built from, else what adding one would use now."""
    ref = docx_certification.page_template(data)
    if ref:
        return ref
    try:
        return cert_page.choice_id(cert_page.page_template_for(db, project))
    except cert_page.TemplateNotFound:
        return cert_page.STANDARD


def _carry_fields(content: docx_certification.CertContent, old: dict, typed: dict, old_lang: str) -> None:
    """Keep what the old page said (and what's typed in the panel) on the page built from another template."""
    kept = {k: v for k, v in old.items() if k in docx_certification.FIELDS and v}
    kept.update({k: v for k, v in typed.items() if v})
    iso = kept.get("date", "")
    if not docx_certification.ISO_DATE.match(iso):
        iso = old.get("date_iso", "")
    try:
        content.day = date.fromisoformat(iso)
        kept["date"] = cert_locale.format_date(content.day, content.lang)
    except ValueError:
        pass
    for name in ("source_language", "target_language"):
        if name in kept and old_lang != content.lang:
            kept[name] = cert_locale.relocalize(kept[name], content.lang)
    content.values.update(kept)


def _refuse_dtp(project: TranslationProject) -> None:
    if is_dtp(project):
        raise HTTPException(status_code=409, detail="An editable copy isn't a translation, so it can't be certified")


def _templates(db: Session, project: TranslationProject) -> list[dict]:
    return [
        {"id": str(c.id), "name": c.file_name, "is_default": bool(c.is_default)}
        for c in cert_page.templates(db, project.team_id)
    ]


@router.get("/{project_id}/document/certification", dependencies=_cert_feature)
def get_certification(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """`template_id` is the page's template ("standard" for the built-in one), or the one an add would use."""
    project = get_user_project_or_404(db, project_id, user)
    data, version = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    fields = docx_certification.read_fields(data)
    return {
        "version": version,
        "present": fields is not None,
        "fields": fields or {},
        "template_id": _current_choice(db, project, data),
        "templates": _templates(db, project),
    }


@router.post("/{project_id}/document/certification", dependencies=_cert_feature)
def add_certification(
    project_id: UUID,
    payload: _CertCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Adds the page; a `template_id` picks the template and is saved on the project for later exports and re-adds."""
    project = get_user_project_or_404(db, project_id, user)
    _refuse_dtp(project)
    cert, template = _page_template(db, project, payload.template_id)
    content = cert_page.content_for_project(db, project, user, template)
    content.template_ref = cert_page.choice_id(cert)

    def change(data, locked_project):
        doc_type = (project.doc_profile or {}).get("document_type", "") if isinstance(project.doc_profile, dict) else ""
        content.values["document"] = docx_certification.guess_document_title(data, content.values["document"], doc_type)
        if payload.template_id is not None:
            cert_page.remember(locked_project, cert)
        return docx_certification.add_certification(data, content)

    new_version = _edit(db, project_id, user, payload.version, "Added the certification page", change)
    fields = dict(content.values, date_iso=content.day.isoformat())
    return {"version": new_version, "present": True, "fields": fields, "template_id": content.template_ref}


@router.put("/{project_id}/document/certification", dependencies=_cert_feature)
def update_certification(
    project_id: UUID,
    payload: _CertUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Updates the fields in place. A different `template_id` rebuilds the page from that template, keeping the values."""
    typed = payload.fields.model_dump(exclude_none=True)
    switch = None
    _refuse_dtp(get_user_project_or_404(db, project_id, user))
    if payload.template_id is not None:
        project = get_user_project_or_404(db, project_id, user)
        cert, template = _page_template(db, project, payload.template_id)
        switch = (cert, cert_page.content_for_project(db, project, user, template))
        switch[1].template_ref = cert_page.choice_id(cert)
    lang = {}

    def change(data, locked_project):
        lang["code"] = cert_locale.detect_language(docx_certification.page_text(data)) or cert_locale.cert_language(
            locked_project.target_language
        )
        if switch is not None:
            cert, content = switch
            old = docx_certification.read_fields(data)
            if old is None:
                raise DocxEditError("There is no certification page")
            cert_page.remember(locked_project, cert)
            if _current_choice(db, locked_project, data) != content.template_ref:
                _carry_fields(content, old, typed, lang["code"])
                return docx_certification.add_certification(data, content)
        out, _ = docx_certification.update_fields(data, typed, lang["code"])
        return out

    note = "Changed the certification template" if switch is not None else "Updated the certification page"
    new_version = _edit(db, project_id, user, payload.version, note, change)
    project = get_user_project_or_404(db, project_id, user)
    data, _ = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    return {
        "version": new_version,
        "present": True,
        "fields": docx_certification.read_fields(data) or {},
        "template_id": _current_choice(db, project, data),
    }


@router.delete("/{project_id}/document/certification", dependencies=_cert_feature)
def delete_certification(
    project_id: UUID,
    version: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    change = lambda data, _p: docx_certification.remove_certification(data)
    return {"version": _edit(db, project_id, user, version, "Removed the certification page", change)}
