from fastapi import APIRouter, Depends, HTTPException
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
    # Tenant guard — IDOR-safe (CRIT-2): only return projects on the
    # caller's team, otherwise 404 (don't reveal existence cross-tenant).
    project = get_user_project_or_404(db, project_id, current_user)

    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project_id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    if not segments:
        raise HTTPException(status_code=404, detail="No segments found")

    # Only approved segments make it into the export — that's how the
    # editor signals "ready to ship". Edits to translated_text done in
    # the editor land in the DB before this point, so they're picked up
    # automatically.
    valid_segments = [
        s for s in segments
        if s.translated_text
        and s.translated_text.strip()
        and bool(s.approved)
    ]
    if not valid_segments:
        raise HTTPException(
            status_code=400,
            detail=(
                "No approved segments yet. Approve segments in the editor "
                "(green tick) before exporting."
            ),
        )

    try:
        file_buffer = generate_docx(
            valid_segments,
            current_user.email,
            project=project,
            user=current_user,
        )
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
    # Tenant guard — IDOR-safe (CRIT-2): only return projects on the
    # caller's team, otherwise 404 (don't reveal existence cross-tenant).
    project = get_user_project_or_404(db, project_id, current_user)

    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project_id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    if not segments:
        raise HTTPException(status_code=404, detail="No segments found")

    # Only approved segments make it into the export — see the DOCX route
    # above for the full reasoning.
    valid_segments = [
        s for s in segments
        if s.translated_text
        and s.translated_text.strip()
        and bool(s.approved)
    ]
    if not valid_segments:
        raise HTTPException(
            status_code=400,
            detail=(
                "No approved segments yet. Approve segments in the editor "
                "(green tick) before exporting."
            ),
        )

    try:
        file_buffer = generate_pdf(
            valid_segments,
            current_user.email,
            project=project,
            user=current_user,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {str(e)}")

    return StreamingResponse(
        file_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=translation_{project_id}.pdf"
        },
    )