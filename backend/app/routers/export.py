import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
from fastapi.responses import Response, StreamingResponse

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.dependencies.tenant import get_user_project_or_404
from app.models.translation_segment import TranslationSegment
from app.models.project import ProjectStatus, TranslationProject, is_dtp
from app.models.user import User
from app.services import dtp_export

from app.services.export_service import generate_docx, generate_pdf
from app.services.learning import capture_template_in_background

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Export"])


def _finished_project(db: Session, project_id: UUID, user: User) -> TranslationProject:
    project = get_user_project_or_404(db, project_id, user)
    # Without a finished translation the export would be a certification page certifying nothing.
    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="The translation isn't finished yet")
    return project


def render_export(db: Session, project: TranslationProject, user: User, fmt: str):
    """The exact file the single-document export downloads (certification page included)."""
    if is_dtp(project):
        return dtp_export.render(db, project, user, fmt)
    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project.id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    valid_segments = [s for s in segments if s.translated_text and s.translated_text.strip()]
    build = generate_pdf if fmt == "pdf" else generate_docx
    return build(valid_segments, user.email, project=project, user=user)





@router.get(
    "/{project_id}/export",
    dependencies=[Depends(require_feature("download_translation"))],
)
def export_docx_route(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):


    project = _finished_project(db, project_id, current_user)

    try:
        file_buffer = render_export(db, project, current_user, "docx")
    except Exception:
        logger.exception("Request failed")
        raise HTTPException(status_code=500, detail="DOCX export failed")

    background_tasks.add_task(capture_template_in_background, project.id, current_user.id)
    return StreamingResponse(
        file_buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=translation_{project_id}.docx"
        },
    )





@router.get(
    "/{project_id}/export/pdf",
    dependencies=[Depends(require_feature("download_translation"))],
)
def export_pdf_route(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):


    project = _finished_project(db, project_id, current_user)

    try:
        file_buffer = render_export(db, project, current_user, "pdf")
    except Exception:
        logger.exception("Request failed")
        raise HTTPException(status_code=500, detail="PDF export failed")

    background_tasks.add_task(capture_template_in_background, project.id, current_user.id)
    return StreamingResponse(
        file_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=translation_{project_id}.pdf"
        },
    )


@router.get(
    "/{project_id}/export/delivery.pdf",
    dependencies=[Depends(require_feature("download_translation"))],
)
def export_delivery_pdf_route(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    include_original: bool = Query(True),
    order: str = Query("translation_first", pattern="^(translation_first|original_first)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.delivery_pdf import DeliveryError, build_delivery_pdf, delivery_filename
    from app.services.s3_service import _attachment

    project = _finished_project(db, project_id, current_user)

    try:
        data = build_delivery_pdf(db, project, current_user, include_original=include_original, order=order)
    except DeliveryError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Request failed")
        raise HTTPException(status_code=500, detail="Delivery PDF export failed")

    background_tasks.add_task(capture_template_in_background, project.id, current_user.id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": _attachment(delivery_filename(project))},
    )












