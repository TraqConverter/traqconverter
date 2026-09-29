import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from fastapi.responses import StreamingResponse

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.dependencies.tenant import get_user_project_or_404
from app.models.translation_segment import TranslationSegment
from app.models.project import TranslationProject
from app.models.user import User

from app.services.export_service import generate_docx, generate_pdf
from app.services.learning import capture_template_in_background

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Export"])


def render_export(db: Session, project: TranslationProject, user: User, fmt: str):
    """The exact file the single-document export downloads (certification page included)."""
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


    project = get_user_project_or_404(db, project_id, current_user)

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


    project = get_user_project_or_404(db, project_id, current_user)

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












@router.post(
    "/{project_id}/build-rebuild-docx",
    dependencies=[Depends(require_feature("download_translation"))],
)
def build_rebuild_docx(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import tempfile
    import os
    from pathlib import Path
    from app.services.s3_service import (
        upload_file_to_s3,
        generate_presigned_download_url,
    )

    project = get_user_project_or_404(db, project_id, current_user)

    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project_id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )


    valid_segments = [
        s for s in segments
        if s.translated_text and s.translated_text.strip()
    ]

    try:
        file_buffer = generate_docx(
            valid_segments,
            current_user.email,
            project=project,
            user=current_user,
        )
    except Exception:
        logger.exception("Request failed")
        raise HTTPException(
            status_code=500, detail="DOCX build failed"
        )


    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".docx", delete=False
        ) as tmp:
            tmp.write(file_buffer.getvalue())
            tmp_path = Path(tmp.name)

        key = upload_file_to_s3(tmp_path)



        project.output_file = key
        db.commit()
        db.refresh(project)
    finally:
        if tmp_path and tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass



    url = generate_presigned_download_url(key, inline=True)
    return {
        "url": url,
        "kind": "docx",
        "filename": key.rsplit("/", 1)[-1],
    }