"""Review before delivery: source page images, the source-to-translation map and the pre-delivery checklist."""
import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.rate_limit import user_rate_limit
from app.dependencies.tenant import get_user_project_or_404
from app.models.user import User
from app.routers.document import _initial_builder
from app.services import document_editor, review_checks, source_map, source_pages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Review"])

ITEM_ID = r"^[0-9a-f]{12}$"
_checks_limit = [Depends(user_rate_limit("review_checks", max_requests=600, per_seconds=3600))]


def _document(db: Session, project_id: UUID, user: User):
    project = get_user_project_or_404(db, project_id, user)
    data, _ = document_editor.current_document(db, project, user, _initial_builder(db, project, user))
    return project, data


def _refresh_map(db: Session, project, data: bytes, background: BackgroundTasks) -> dict:
    smap, todo = source_map.refresh(db, project, data)
    if todo:
        background.add_task(source_map.run_vision, project.id, todo)
    return smap


@router.get("/{project_id}/source/pages")
def source_page_list(project_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = get_user_project_or_404(db, project_id, user)
    info = source_pages.page_info(project)
    return {"available": info["available"], "count": info["count"], "pages": info["pages"], "kind": info.get("kind")}


@router.get("/{project_id}/source/pages/{index}.png")
def source_page_image(
    project_id: UUID,
    index: int = PathParam(..., ge=0, le=999),
    scale: float = Query(2.0, ge=0.1, le=8),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, user)
    png = source_pages.render_page(project, index, scale)
    if png is None:
        raise HTTPException(status_code=404, detail="Page not available")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{project_id}/source/map", dependencies=_checks_limit)
def source_region_map(
    project_id: UUID,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project, data = _document(db, project_id, user)
    smap = _refresh_map(db, project, data, background)
    state = source_map.get_state(db, project)
    paras = source_map.document_paragraphs(data)
    view = source_map.public_view(smap, paras, state.map_revision or 0, project.document_version or 0)
    db.commit()
    return view


@router.get("/{project_id}/checks", dependencies=_checks_limit)
def pre_delivery_checks(
    project_id: UUID,
    background: BackgroundTasks,
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project, data = _document(db, project_id, user)
    smap = _refresh_map(db, project, data, background)
    return review_checks.run(db, project, user, data, smap, refresh=refresh)


@router.post("/{project_id}/checks/{item_id}/dismiss")
def dismiss_check(
    project_id: UUID,
    item_id: str = PathParam(..., pattern=ITEM_ID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, user)
    review_checks.dismiss(db, project, item_id, True)
    return {"id": item_id, "dismissed": True, "document_version": project.document_version or 0}


@router.delete("/{project_id}/checks/{item_id}/dismiss")
def restore_check(
    project_id: UUID,
    item_id: str = PathParam(..., pattern=ITEM_ID),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, user)
    review_checks.dismiss(db, project, item_id, False)
    return {"id": item_id, "dismissed": False, "document_version": project.document_version or 0}
