from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.tenant import (
    get_user_project_or_404,
    assert_project_access,
)
from app.models.translation_segment import TranslationSegment
from app.models.project import TranslationProject
from app.models.user import User

from app.services.translation_memory_service import store_tm_entry

router = APIRouter(prefix="/segments", tags=["Segments"])


class SegmentUpdate(BaseModel):
    translated_text: str


class SegmentRetranslate(BaseModel):
    # Optional steering for the AI — e.g. "Make this more formal",
    # "Use 'Municipality of' instead of 'City of'", "Translate as a
    # full sentence". Appended to the system prompt so users can
    # nudge a single segment without changing the project glossary.
    instructions: str | None = None


# =========================================
# GET SEGMENTS FOR PROJECT — team scoped
# =========================================

@router.get("/project/{project_id}")
def get_segments(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project.id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )
    return [
        {
            "id": str(s.id),
            "segment_index": s.segment_index,
            "source_text": s.source_text,
            "translated_text": s.translated_text or "",
            "approved": bool(getattr(s, "approved", False)),
            "tm_pct": getattr(s, "tm_pct", None),
        }
        for s in segments
    ]


# =========================================
# UPDATE SEGMENT — team scoped (CRIT-1 fix)
# =========================================

@router.patch("/{segment_id}")
def update_segment(
    segment_id: UUID,
    data: SegmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    segment = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.id == segment_id)
        .first()
    )
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == segment.project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Tenant guard — reject segments that don't belong to a team this user is on.
    assert_project_access(db, project, current_user)

    segment.translated_text = data.translated_text
    db.commit()
    db.refresh(segment)

    # Store in Translation Memory (team scoped — same as before, but now
    # the underlying segment is verified to belong to the caller's team).
    try:
        store_tm_entry(
            db=db,
            team_id=project.team_id,
            source_language=project.source_language,
            target_language=project.target_language,
            source_text=segment.source_text,
            translated_text=data.translated_text,
        )
    except Exception:
        # TM write failures shouldn't fail the user's edit.
        pass

    return {
        "id": str(segment.id),
        "source_text": segment.source_text,
        "translated_text": segment.translated_text,
    }


# =========================================
# AI RETRANSLATE — single segment
# =========================================

@router.post("/{segment_id}/retranslate")
def retranslate_segment(
    segment_id: UUID,
    data: SegmentRetranslate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run AI translation on one segment. Optionally accepts free-
    text steering (`instructions`) so the user can ask for a more
    formal tone, an alternative term, a full sentence, etc., without
    editing the project glossary.
    """
    from app.services.ai_translation_service import (
        translate_text,
        _call_model,
        humanize_lang,
    )

    segment = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.id == segment_id)
        .first()
    )
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == segment.project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    assert_project_access(db, project, current_user)

    src_text = segment.source_text or ""
    if not src_text.strip():
        raise HTTPException(
            status_code=400, detail="Source text is empty"
        )

    instructions = (data.instructions or "").strip()

    try:
        if instructions:
            # Custom-instructions path — build the prompt directly so
            # the user steering takes effect. Reuses the same model
            # router as translate_text/translate_batch.
            src_name = humanize_lang(project.source_language)
            tgt_name = humanize_lang(project.target_language)
            system_prompt = (
                f"You are a professional translator. Translate from "
                f"{src_name} to {tgt_name}. The output MUST be "
                f"written in {tgt_name}. Return ONLY the translated "
                f"text — no preamble, no quotes, no commentary.\n\n"
                f"USER INSTRUCTIONS (apply these strictly):\n{instructions}"
            )
            new_translation = _call_model(
                model_key=getattr(project, "model", None),
                system=system_prompt,
                user=src_text,
                max_tokens=2048,
            )
        else:
            # No instructions — let translate_text apply glossary +
            # default rules.
            new_translation = translate_text(
                text=src_text,
                source_lang=project.source_language,
                target_lang=project.target_language,
                db=db,
                project=project,
            )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Retranslation failed: {e}"
        )

    segment.translated_text = (new_translation or "").strip()
    # Re-translation invalidates a previous approval — the user
    # should review the new text before approving.
    segment.approved = False
    db.commit()
    db.refresh(segment)

    return {
        "id": str(segment.id),
        "source_text": segment.source_text,
        "translated_text": segment.translated_text,
        "approved": bool(segment.approved),
    }
