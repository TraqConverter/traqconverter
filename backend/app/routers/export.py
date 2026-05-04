from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from fastapi.responses import StreamingResponse

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.models.translation_segment import TranslationSegment
from app.models.project import TranslationProject
from app.models.user import User

from app.services.export_service import generate_docx, generate_pdf

router = APIRouter(prefix="/projects", tags=["Export"])


# =========================================
# EXPORT DOCX (REAL + CERTIFIED, layout-preserving when possible)
# =========================================
@router.get(
    "/{project_id}/export",
    dependencies=[Depends(require_feature("download_translation"))],
)
def export_docx_route(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project_id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    if not segments:
        raise HTTPException(status_code=404, detail="No segments found")

    valid_segments = [
        s for s in segments if s.translated_text and s.translated_text.strip()
    ]
    if not valid_segments:
        raise HTTPException(status_code=400, detail="No translated content available")

    try:
        file_buffer = generate_docx(valid_segments, current_user.email, project=project)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX export failed: {str(e)}")

    return StreamingResponse(
        file_buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=translation_{project_id}.docx"
        },
    )


# =========================================
# EXPORT PDF (REAL + CERTIFIED, layout-preserving when possible)
# =========================================
@router.get(
    "/{project_id}/export/pdf",
    dependencies=[Depends(require_feature("download_translation"))],
)
def export_pdf_route(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project_id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    if not segments:
        raise HTTPException(status_code=404, detail="No segments found")

    valid_segments = [
        s for s in segments if s.translated_text and s.translated_text.strip()
    ]
    if not valid_segments:
        raise HTTPException(status_code=400, detail="No translated content available")

    try:
        file_buffer = generate_pdf(valid_segments, current_user.email, project=project)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {str(e)}")

    return StreamingResponse(
        file_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=translation_{project_id}.pdf"
        },
    )