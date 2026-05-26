import logging
import os
from uuid import UUID
from pathlib import Path
from app.models.translation_segment import TranslationSegment

from fastapi import Form
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Depends,
    HTTPException,
    BackgroundTasks,
    Header,
)

from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature
from app.dependencies.tenant import get_user_project_or_404
from app.models.project import TranslationProject, ProjectStatus
from app.models.user import User
from app.models.team import Team
from app.schemas.project import ProjectStatusResponse

from app.core.file_validation import validate_file_extension, validate_file_size
from app.core.page_counter import get_page_count

from app.services.storage_service import save_file_locally
from app.services.s3_service import upload_file_to_s3, generate_presigned_download_url
from app.services.queue_service import enqueue_translation_job

from fastapi.responses import StreamingResponse
from app.services.export_service import generate_docx
from app.services.export_service import generate_pdf

from app.services.credit_service import (
    CreditService,
    WalletNotFoundError,
    InsufficientCreditsError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])


# ============================================================
# UPLOAD PROJECT
# ============================================================

@router.post("/upload")
async def upload_project(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),

    # ✅ FIX 1: Provide defaults so frontend doesn’t break
    source_language: str = Form("English"),
    target_language: str = Form("Spanish"),
    model: str = Form("balanced"),

    # New-project page toggles — persisted on the project so the worker
    # can honour them at translation time.
    use_tm: bool = Form(True),
    apply_glossary: bool = Form(True),
    request_certification: bool = Form(False),

    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_file_extension(file.filename)
    validate_file_size(file)

    file_path = None
    project = None

    try:

        # ----------------------------------------------------
        # Idempotency Check
        # ----------------------------------------------------
        if idempotency_key:
            existing_project = (
                db.query(TranslationProject)
                .filter(TranslationProject.idempotency_key == idempotency_key)
                .first()
            )

            if existing_project:
                logger.info("Idempotent replay detected")
                return {
                    "message": "Project already created (idempotent replay)",
                    "project_id": str(existing_project.id),
                    "pages": existing_project.page_count,
                    "credits_used": existing_project.credits_used,
                }

        # ----------------------------------------------------
        # Get Team (CRITICAL FIX)
        # ----------------------------------------------------
        team = (
            db.query(Team)
            .filter(Team.owner_id == current_user.id)
            .first()
        )

        if not team:
            raise HTTPException(status_code=400, detail="Team not found")

        # ----------------------------------------------------
        # Save File Locally
        # ----------------------------------------------------
        file_path, _ = save_file_locally(file, str(team.id))

        # ----------------------------------------------------
        # Upload To S3
        # ----------------------------------------------------
        s3_key = upload_file_to_s3(Path(file_path))
        logger.info(f"S3 upload successful: {s3_key}")

        # ----------------------------------------------------
        # Count Pages (SAFE GUARD)
        # ----------------------------------------------------
        try:
            page_count = get_page_count(file_path)
        except Exception:
            page_count = 1  # 🔥 fallback so upload never fails

        credits_required = max(1, page_count)

        # ----------------------------------------------------
        # Create Project (FIXED MODEL FIELD)
        # ----------------------------------------------------
        project = TranslationProject(
            user_id=current_user.id,
            team_id=team.id,
            file_name=file.filename,
            file_path=s3_key,
            page_count=page_count,
            credits_used=credits_required,
            idempotency_key=idempotency_key,

            source_language=source_language,
            target_language=target_language,
            model=model,  # ✅ REQUIRED FIELD

            # Per-project options from the new-project page toggles.
            use_tm=use_tm,
            apply_glossary=apply_glossary,
            add_certification=request_certification,

            status=ProjectStatus.PENDING,
            progress_percent=0,
        )

        db.add(project)
        db.flush()

        # ----------------------------------------------------
        # Deduct Credits — superusers / admins bypass the wallet
        # entirely so the operator account never runs out.
        # ----------------------------------------------------
        is_staff = (current_user.role or "").upper() in (
            "SUPERUSER", "SUPER_ADMIN", "ADMIN",
        )
        if is_staff:
            new_balance = -1  # signals "unlimited"
        else:
            try:
                new_balance = CreditService.deduct_credits(
                    db=db,
                    team_id=str(team.id),
                    amount=credits_required,
                    reference_id=str(project.id),
                )
            except WalletNotFoundError:
                raise HTTPException(status_code=404, detail="Credit wallet not found")
            except InsufficientCreditsError:
                raise HTTPException(status_code=400, detail="Insufficient credits")

        # ----------------------------------------------------
        # Commit
        # ----------------------------------------------------
        db.commit()
        db.refresh(project)

        project_id = str(project.id)

        if file_path and os.path.exists(file_path):
            os.remove(file_path)

    except HTTPException:
        db.rollback()
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise

    except Exception as e:
        db.rollback()

        logger.exception("Upload failed")
        # Audit Low fix: was a print-with-emoji; use the logger instead.
        logger.error("Upload failed: %s", e)

        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        raise HTTPException(status_code=400, detail=str(e))

    # ----------------------------------------------------
    # Trigger Worker
    # ----------------------------------------------------
    background_tasks.add_task(
        enqueue_translation_job,
        project_id,
        s3_key
    )

    logger.info(f"Project {project_id} queued")

    return {
        "message": "Project created",
        "project_id": project_id,
        "pages": page_count,
        "credits_used": credits_required,
        "remaining_credits": new_balance,
    }

# ============================================================
# LIST PROJECTS
# ============================================================

@router.get("/")
def list_projects(
    assignee: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List projects scoped to the user's team.

    The current_user can see anything they own OR are assigned to. Optional
    `assignee` query param filters the result to a specific team member's
    work, or `me` for the current user's assigned-to-them queue.
    """
    from app.models.team_member import TeamMember
    from app.models.team import Team

    # Resolve the team this user belongs to (owner or member)
    team = db.query(Team).filter(Team.owner_id == current_user.id).first()
    if not team:
        membership = (
            db.query(TeamMember).filter(TeamMember.user_id == current_user.id).first()
        )
        if membership:
            team = db.query(Team).filter(Team.id == membership.team_id).first()

    base = db.query(TranslationProject).order_by(TranslationProject.created_at.desc())
    if team:
        base = base.filter(TranslationProject.team_id == team.id)
    else:
        base = base.filter(TranslationProject.user_id == current_user.id)

    if assignee == "me":
        base = base.filter(TranslationProject.assignee_id == current_user.id)
    elif assignee == "unassigned":
        base = base.filter(TranslationProject.assignee_id.is_(None))
    elif assignee:
        base = base.filter(TranslationProject.assignee_id == assignee)

    projects = base.limit(50).all()

    # Pre-fetch BOTH assignee and owner user rows so we can render
    # names/emails without N+1. The frontend uses assignee when set
    # (someone's actively working on it) and falls back to the project
    # creator otherwise — the dashboard's "TEAM" column needs real
    # initials rather than the old "NL" placeholder.
    related_ids = {p.assignee_id for p in projects if p.assignee_id}
    related_ids |= {p.user_id for p in projects if p.user_id}
    users_by_id = {}
    if related_ids:
        for u in db.query(User).filter(User.id.in_(related_ids)).all():
            users_by_id[str(u.id)] = u

    result = []
    for p in projects:
        progress = 0
        if p.total_segments and p.total_segments > 0:
            progress = int((p.translated_segments / p.total_segments) * 100)
        if p.status == ProjectStatus.COMPLETED:
            progress = 100

        a = users_by_id.get(str(p.assignee_id)) if p.assignee_id else None
        o = users_by_id.get(str(p.user_id)) if p.user_id else None

        result.append({
            "id": str(p.id),
            "filename": p.file_name,
            "status": p.status,
            # review_status is the human-review axis. The frontend
            # uses it to render the "In review" / "Certified" pill
            # when the worker has finished (status==COMPLETED).
            "review_status": p.review_status or "DRAFT",
            "progress": progress,
            "source_lang": p.source_language,
            "target_lang": p.target_language,
            "page_count": p.page_count,
            "credits_used": p.credits_used,
            "created_at": p.created_at,
            "assignee_id": str(p.assignee_id) if p.assignee_id else None,
            "assignee": (
                {
                    "id": str(a.id),
                    "email": a.email,
                    "full_name": a.full_name,
                }
                if a
                else None
            ),
            "owner": (
                {
                    "id": str(o.id),
                    "email": o.email,
                    "full_name": o.full_name,
                }
                if o
                else None
            ),
        })

    return result


# ============================================================
# ASSIGN PROJECT TO A TEAM MEMBER
# ============================================================

class _AssignPayload(BaseModel):
    assignee_id: str | None = None


@router.patch("/{project_id}/assign")
def assign_project(
    project_id: UUID,
    data: _AssignPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.team_member import TeamMember
    from app.models.team import Team

    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Caller must own the team or be a member of it
    team = db.query(Team).filter(Team.id == project.team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    is_owner = team.owner_id == current_user.id
    is_member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team.id, TeamMember.user_id == current_user.id)
        .first()
        is not None
    )
    if not (is_owner or is_member):
        raise HTTPException(status_code=403, detail="You can't assign this project")

    if data.assignee_id is None:
        project.assignee_id = None
    else:
        # Verify the assignee is on the same team
        target = db.query(User).filter(User.id == data.assignee_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Assignee not found")

        on_team = (
            target.id == team.owner_id
            or db.query(TeamMember)
            .filter(
                TeamMember.team_id == team.id, TeamMember.user_id == target.id
            )
            .first()
            is not None
        )
        if not on_team:
            raise HTTPException(
                status_code=400, detail="That user isn't on this team"
            )
        project.assignee_id = target.id

    db.commit()
    db.refresh(project)
    return {
        "project_id": str(project.id),
        "assignee_id": str(project.assignee_id) if project.assignee_id else None,
    }


# ============================================================
# GET PROJECT STATUS
# ============================================================

@router.get("/{project_id}")
def get_project_status(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    project = (
        db.query(TranslationProject)
        .filter(
            TranslationProject.id == project_id,
            TranslationProject.user_id == current_user.id,
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    progress = 0
    if project.total_segments and project.total_segments > 0:
        progress = int(
            (project.translated_segments / project.total_segments) * 100
        )

    # Real per-segment counts so the editor toolbar doesn't show fake stats.
    total = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project.id)
        .count()
    )
    translated = (
        db.query(TranslationSegment)
        .filter(
            TranslationSegment.project_id == project.id,
            TranslationSegment.translated_text.isnot(None),
            TranslationSegment.translated_text != "",
        )
        .count()
    )
    approved = (
        db.query(TranslationSegment)
        .filter(
            TranslationSegment.project_id == project.id,
            TranslationSegment.approved.is_(True),
        )
        .count()
    )

    # Average TM match across segments that had a hit.
    tm_hits = (
        db.query(TranslationSegment.tm_pct)
        .filter(
            TranslationSegment.project_id == project.id,
            TranslationSegment.tm_pct.isnot(None),
        )
        .all()
    )
    tm_avg = (
        round(sum(int(r[0]) for r in tm_hits) / len(tm_hits)) if tm_hits else 0
    )

    # Resolve assignee user once for the avatar circle.
    assignee_payload = None
    if project.assignee_id:
        a = db.query(User).filter(User.id == project.assignee_id).first()
        if a:
            assignee_payload = {
                "id": str(a.id),
                "email": a.email,
                "full_name": a.full_name,
            }

    # Resolve owner / uploader so the editor can show their initials too.
    uploader_payload = None
    owner = db.query(User).filter(User.id == project.user_id).first()
    if owner:
        uploader_payload = {
            "id": str(owner.id),
            "email": owner.email,
            "full_name": owner.full_name,
        }

    return {
        "id": str(project.id),
        "status": project.status,
        "review_status": project.review_status or "DRAFT",
        "progress_percent": progress,
        "retry_count": project.retry_count,
        "created_at": project.created_at,
        "file_name": project.file_name,
        "source_language": project.source_language,
        "target_language": project.target_language,
        "stats": {
            "total_segments": total,
            "translated_segments": translated,
            "approved_segments": approved,
            "tm_average_pct": tm_avg,
        },
        "assignee": assignee_payload,
        "uploader": uploader_payload,
    }

# ============================================================
# GET PROJECT SEGMENTS
# ============================================================

@router.get("/{project_id}/segments")
def get_project_segments(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 🔒 Ensure project belongs to user
    project = (
        db.query(TranslationProject)
        .filter(
            TranslationProject.id == project_id,
            TranslationProject.user_id == current_user.id,
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 📄 Get segments
    segments = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project_id)
        .order_by(TranslationSegment.segment_index)
        .all()
    )

    return [
        {
            "id": str(s.id),
            "segment_index": s.segment_index,
            "source_text": s.source_text,
            "translated_text": s.translated_text or "",
            "approved": bool(s.approved),
            "tm_pct": s.tm_pct,
        }
        for s in segments
    ]


# ============================================================
# TOGGLE SEGMENT APPROVAL (used by editor's green-tick action)
# ============================================================

class _ApprovePayload(BaseModel):
    approved: bool


@router.patch("/{project_id}/segments/{segment_id}/approve")
def approve_segment(
    project_id: UUID,
    segment_id: UUID,
    data: _ApprovePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Audit HIGH-3: scope by team, not creator. Assigned teammates can
    # see/approve/certify/download projects too.
    project = get_user_project_or_404(db, project_id, current_user)

    seg = (
        db.query(TranslationSegment)
        .filter(
            TranslationSegment.id == segment_id,
            TranslationSegment.project_id == project_id,
        )
        .first()
    )
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")

    seg.approved = bool(data.approved)
    db.commit()
    db.refresh(seg)
    return {"id": str(seg.id), "approved": seg.approved}


# ============================================================
# UPDATE PROJECT REVIEW STATUS (DRAFT / IN_REVIEW / CERTIFIED)
# ============================================================

class _ReviewStatusPayload(BaseModel):
    status: str


@router.patch("/{project_id}/review-status")
def update_review_status(
    project_id: UUID,
    data: _ReviewStatusPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed = {"DRAFT", "IN_REVIEW", "CERTIFIED"}
    new_status = (data.status or "").strip().upper()
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid review status")

    # Audit HIGH-3: scope by team, not creator. Assigned teammates can
    # see/approve/certify/download projects too.
    project = get_user_project_or_404(db, project_id, current_user)

    project.review_status = new_status
    db.commit()
    db.refresh(project)
    return {"id": str(project.id), "review_status": project.review_status}


# ============================================================
# CERTIFY & DELIVER — flips review_status to CERTIFIED. Pro only.
# ============================================================

@router.post(
    "/{project_id}/certify",
    dependencies=[Depends(require_feature("certifications"))],
)
def certify_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Audit HIGH-3: scope by team, not creator. Assigned teammates can
    # see/approve/certify/download projects too.
    project = get_user_project_or_404(db, project_id, current_user)

    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="The translation must finish before it can be certified.",
        )

    project.review_status = "CERTIFIED"
    db.commit()
    db.refresh(project)
    return {
        "id": str(project.id),
        "review_status": project.review_status,
        "certified_at": project.created_at.isoformat()
        if project.created_at
        else None,
    }


# ============================================================
# DOWNLOAD PROJECT RESULT — gated on download_translation feature.
# DOCX/PDF export endpoints live in app.routers.export to avoid
# duplicate routes — they consume the layout-preserving rebuild
# that the worker uploads to S3.
# ============================================================

# ============================================================
# SOURCE PREVIEW — returns a short-lived signed URL the editor can
# load into an <iframe>/<img> to show the ORIGINAL document next to
# the rebuilt translation. No download gating — viewing the source
# is always allowed if the user can see the project at all.
# ============================================================
@router.get("/{project_id}/source-url")
def get_source_url(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    if not project.file_path:
        raise HTTPException(status_code=404, detail="Source file not available")
    # inline=True so the browser renders the PDF/image in the iframe
    # rather than downloading it.
    url = generate_presigned_download_url(project.file_path, inline=True)
    # Hand the frontend a hint about how to render the file so it can
    # choose <iframe> for PDFs and <img> for images.
    fname = (project.file_name or "").lower()
    if fname.endswith(".pdf"):
        kind = "pdf"
    elif fname.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        kind = "image"
    else:
        kind = "other"
    return {"url": url, "kind": kind, "filename": project.file_name}


# ============================================================
# REBUILD PREVIEW — returns a signed URL to the rebuild output file
# so the editor's Compare view can show it next to the original.
# This is purely a preview / viewing call (no download-feature
# gating) so users on any plan can verify the rebuild visually.
# ============================================================
@router.get("/{project_id}/rebuild-url")
def get_rebuild_url(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    if not project.output_file:
        # The worker hasn't produced an output yet (project still
        # processing or failed). Tell the frontend so it can show a
        # helpful message rather than a broken iframe.
        return {"url": None, "kind": "none", "filename": None}
    # inline=True so the browser renders the rebuild in the iframe
    # rather than triggering a download.
    url = generate_presigned_download_url(project.output_file, inline=True)
    name = (project.output_file or "").rsplit("/", 1)[-1].lower()
    if name.endswith(".pdf"):
        kind = "pdf"
    elif name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        kind = "image"
    elif name.endswith(".docx"):
        kind = "docx"
    else:
        kind = "other"
    return {"url": url, "kind": kind, "filename": name}


@router.get(
    "/{project_id}/download",
    dependencies=[Depends(require_feature("download_translation"))],
)
def download_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Audit HIGH-3: scope by team, not creator. Assigned teammates can
    # see/approve/certify/download projects too.
    project = get_user_project_or_404(db, project_id, current_user)

    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=400, detail="Project processing not completed yet"
        )

    if not project.output_file:
        raise HTTPException(status_code=404, detail="Output file not available")

    download_url = generate_presigned_download_url(project.output_file)
    return {"download_url": download_url}


# ============================================================
# DELETE PROJECT
# ============================================================

# ============================================================
# RENAME PROJECT — updates the display file_name shown in the UI.
# Doesn't touch the underlying storage key (project.file_path) so
# the original document and any rebuild remain reachable.
# ============================================================

class _RenameProjectPayload(BaseModel):
    file_name: str


@router.patch("/{project_id}")
def rename_project(
    project_id: UUID,
    data: _RenameProjectPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)

    new_name = (data.file_name or "").strip()
    if not new_name:
        raise HTTPException(
            status_code=400, detail="file_name can't be empty"
        )
    # Keep an extension on the visible name so DOCX/PDF export
    # filenames don't get awkward — if the user dropped it, splice
    # the original extension back on.
    original_ext = ""
    if project.file_name and "." in project.file_name:
        original_ext = "." + project.file_name.rsplit(".", 1)[-1]
    if original_ext and not new_name.lower().endswith(original_ext.lower()):
        new_name = new_name + original_ext

    project.file_name = new_name[:255]  # keep it sensible
    db.commit()
    db.refresh(project)
    return {"id": str(project.id), "file_name": project.file_name}


@router.delete("/{project_id}")
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Audit HIGH-3: scope by team, not creator. Assigned teammates can
    # see/approve/certify/download projects too.
    project = get_user_project_or_404(db, project_id, current_user)

    db.delete(project)
    db.commit()

    return {"message": "Project deleted successfully"}
