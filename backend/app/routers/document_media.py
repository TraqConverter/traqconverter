"""Pictures, stamps and the certification page inside the editable translated document."""
import logging
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import Path as PathParam
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.dependencies.rate_limit import user_rate_limit
from app.dependencies.tenant import get_user_project_or_404
from app.models.certification import Certification
from app.models.document_version import DocumentVersion
from app.models.media_asset import MediaAsset
from app.models.project import TranslationProject, is_dtp
from app.models.user import User
from app.routers.document import StampUnavailable, _initial_builder, _locked_project, _require_version, team_stamp
from app.services import (
    cert_locale,
    cert_page,
    docx_certification,
    docx_images,
    docx_page_stamp,
    document_editor,
    media_library,
)
from app.services.docx_blocks import DocxEditError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Document"])

BLOCK_ID = r"^_b[0-9a-f]{8}$"
IMAGE_ID = r"^img_[0-9a-f]{8}$"
Position = Literal["before", "after", "inline"]
Align = Literal["left", "center", "right"]
# "page": offsets from the page's top-left corner, so the picture sits where the editor showed it, whatever the text flow.
Relative = Literal["paragraph", "page"]
_cert_feature = [Depends(require_feature("certifications"))]
_media_feature = [Depends(require_feature("media"))]
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
    relative: Relative = "paragraph"


class _Resize(BaseModel):
    version: int
    width_cm: float = Field(ge=0.5, le=19)


class _Align(BaseModel):
    version: int
    align: Align


class _Duplicate(BaseModel):
    version: int
    target_block_id: str = Field(pattern=BLOCK_ID)
    x_emu: Optional[int] = Field(default=None, ge=-21_600_000, le=21_600_000)
    y_emu: Optional[int] = Field(default=None, ge=-21_600_000, le=21_600_000)
    relative: Relative = "paragraph"

    @model_validator(mode="after")
    def _both_or_neither(self):
        if (self.x_emu is None) != (self.y_emu is None):
            raise ValueError("Give both x_emu and y_emu, or neither")
        return self


class _PagePlacement(BaseModel):
    block_id: str = Field(pattern=BLOCK_ID)
    x_emu: int = Field(ge=-21_600_000, le=21_600_000)
    y_emu: int = Field(ge=-21_600_000, le=21_600_000)


class _CopyToPages(BaseModel):
    version: int
    targets: list[_PagePlacement] = Field(min_length=1, max_length=500)
    relative: Relative = "paragraph"


class _PageStamp(BaseModel):
    version: int
    enabled: Optional[bool] = None
    align: Optional[Align] = None
    width_cm: Optional[float] = Field(
        default=None, ge=docx_page_stamp.MIN_WIDTH_CM, le=docx_page_stamp.MAX_WIDTH_CM
    )
    # A stamp from Media to show instead of the current one.
    asset_id: Optional[UUID] = None


class _Place(BaseModel):
    version: int
    scope: Literal["page", "all"] = "page"
    # The page's first paragraph (or, for "cursor", the paragraph the picture goes after).
    block_id: Optional[str] = Field(default=None, pattern=BLOCK_ID)
    # Every page's first paragraph, for scope "all".
    block_ids: list[Annotated[str, Field(pattern=BLOCK_ID)]] = Field(default_factory=list, max_length=500)
    vertical: Literal["top", "bottom", "cursor"] = "bottom"
    align: Align = "right"
    width_cm: float = Field(default=3.5, ge=0.5, le=19)


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


def _team_asset(db: Session, project: TranslationProject, asset_id: UUID, kind: Optional[str] = None) -> MediaAsset:
    q = db.query(MediaAsset).filter(MediaAsset.id == asset_id, MediaAsset.team_id == project.team_id)
    if kind:
        q = q.filter(MediaAsset.kind == kind)
    asset = q.first()
    if asset is None:
        raise HTTPException(status_code=404, detail="That picture isn't in your media library")
    return asset


def _prepared(asset: MediaAsset) -> docx_images.PreparedImage:
    try:
        return media_library.prepare(asset)
    except media_library.AssetUnavailable:
        raise HTTPException(status_code=502, detail="Couldn't load that picture from storage")


@router.get("/{project_id}/document/media", dependencies=_media_feature)
def list_project_media(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The team's library for the editor's picker, the project's target language first."""
    from app.routers.media import asset_json

    project = get_user_project_or_404(db, project_id, user)
    language = media_library.project_language(project)
    assets = media_library.ranked_for(media_library.team_assets(db, project.team_id), language)
    return {"language": language, "assets": [asset_json(a) for a in assets]}


@router.post("/{project_id}/document/media/{asset_id}/place", dependencies=_media_feature + _upload_limit)
def place_media(
    project_id: UUID,
    asset_id: UUID,
    payload: _Place,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """A media library picture at the cursor, or at a corner of this page or every page: one version, one undo."""
    if payload.vertical == "cursor" and payload.scope != "page":
        raise HTTPException(status_code=422, detail="At the cursor places on this page only")
    if payload.scope == "page" and not payload.block_id:
        raise HTTPException(status_code=422, detail="block_id is required for this page")
    if payload.scope == "all" and not payload.block_ids:
        raise HTTPException(status_code=422, detail="block_ids lists the first paragraph of every page")
    project = get_user_project_or_404(db, project_id, user)
    asset = _team_asset(db, project, asset_id)
    prepared = _prepared(asset)
    made = {"ids": []}

    def change(data, _project):
        if payload.vertical == "cursor":
            out, image_id = docx_images.insert_image(data, prepared, payload.block_id, "after", payload.width_cm, payload.align)
            made["ids"] = [image_id]
            return out
        targets = payload.block_ids if payload.scope == "all" else [payload.block_id]
        out, made["ids"] = docx_images.place_on_pages(data, prepared, targets, payload.vertical, payload.align, payload.width_cm)
        return out

    note = f"Placed {asset.name} on every page" if payload.scope == "all" else f"Placed {asset.name}"
    new_version = _edit(db, project_id, user, payload.version, note, change)
    return {"version": new_version, "image_ids": made["ids"]}


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
    change = lambda data, _p: docx_images.float_image(
        data, image_id, payload.target_block_id, payload.x_emu, payload.y_emu, payload.relative
    )
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


@router.post("/{project_id}/document/images/{image_id}/duplicate")
def duplicate_image(
    project_id: UUID,
    payload: _Duplicate,
    image_id: str = PathParam(pattern=IMAGE_ID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """A copy at the target paragraph sharing the same picture file, at x/y when given, else at the original's offsets."""
    made = {}

    def change(data, _p):
        out, made["id"] = docx_images.duplicate_image(
            data, image_id, payload.target_block_id, payload.x_emu, payload.y_emu, payload.relative
        )
        return out

    new_version = _edit(db, project_id, user, payload.version, "Copied an image", change)
    return {"version": new_version, "image_id": made["id"]}


@router.post("/{project_id}/document/images/{image_id}/copy-to-pages")
def copy_image_to_pages(
    project_id: UUID,
    payload: _CopyToPages,
    image_id: str = PathParam(pattern=IMAGE_ID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One copy per page, each hung from that page's first paragraph at the given offsets: one version, one undo."""
    made = {"ids": []}

    def change(data, _p):
        placements = [(t.block_id, t.x_emu, t.y_emu) for t in payload.targets]
        out, made["ids"] = docx_images.copy_to_blocks(data, image_id, placements, payload.relative)
        return out

    note = "Copied an image to every page"
    new_version = _edit(db, project_id, user, payload.version, note, change)
    return {"version": new_version, "image_ids": made["ids"]}


def _page_stamp_state(db: Session, project: TranslationProject, data: bytes, version: int) -> dict:
    from app.routers.media import asset_json

    stamps = media_library.ranked_for(
        media_library.team_assets(db, project.team_id, "stamp"), media_library.project_language(project)
    )
    keep = ("id", "name", "language", "auto_use", "url")
    return {
        "version": version,
        "available": bool(stamps) and not is_dtp(project),
        **docx_page_stamp.state(data),
        "stamps": [{k: v for k, v in asset_json(a).items() if k in keep} for a in stamps],
    }


@router.get("/{project_id}/document/page-stamp")
def get_page_stamp(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """`managed` is false for documents from before the editable stamp; their export adds it the old way."""
    project = get_user_project_or_404(db, project_id, user)
    data, version = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    return _page_stamp_state(db, project, data, version)


@router.put("/{project_id}/document/page-stamp")
def update_page_stamp(
    project_id: UUID,
    payload: _PageStamp,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """An `asset_id` swaps the stamp's picture for that Media stamp, keeping its place and size."""
    project = get_user_project_or_404(db, project_id, user)
    if is_dtp(project):
        raise HTTPException(status_code=409, detail="An editable copy has no page stamp")
    image = asset_ref = None
    if payload.asset_id is not None:
        asset = _team_asset(db, project, payload.asset_id, kind="stamp")
        image, asset_ref = _prepared(asset), str(asset.id)
    elif payload.enabled:
        try:
            image, asset_ref = team_stamp(db, project)
        except StampUnavailable:
            raise HTTPException(status_code=502, detail="Couldn't load your stamp from storage")
        if image is None:
            raise HTTPException(status_code=404, detail="There's no stamp in Media yet")

    def change(data, _p):
        return docx_page_stamp.update(
            data,
            enabled=payload.enabled,
            align=payload.align,
            width_cm=payload.width_cm,
            image=image,
            asset_id=asset_ref,
            replace_image=payload.asset_id is not None,
        )

    if payload.asset_id is not None:
        note = "Changed the page stamp picture"
    else:
        note = {True: "Turned the page stamp on", False: "Turned the page stamp off"}.get(payload.enabled, "Changed the page stamp")
    _edit(db, project_id, user, payload.version, note, change)
    project = get_user_project_or_404(db, project_id, user)
    data, version = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    return _page_stamp_state(db, project, data, version)


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
