import logging
import os
from uuid import UUID
from pathlib import Path

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

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import TranslationProject, ProjectStatus
from app.models.user import User
from app.models.team import Team
from app.schemas.project import ProjectStatusResponse

from app.core.file_validation import validate_file_extension, validate_file_size
from app.core.page_counter import get_page_count

from app.services.storage_service import save_file_locally
from app.services.s3_service import upload_file_to_s3, generate_presigned_download_url
from app.services.queue_service import enqueue_translation_job

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
        # Get Team
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

        logger.info(f"Uploaded file to S3: {s3_key}")

        # ----------------------------------------------------
        # Count Pages
        # ----------------------------------------------------

        page_count = get_page_count(file_path)

        credits_required = page_count

        # ----------------------------------------------------
        # Create Project
        # ----------------------------------------------------

        project = TranslationProject(
            user_id=current_user.id,
            team_id=team.id,
            file_name=file.filename,
            file_path=s3_key,
            page_count=page_count,
            credits_used=credits_required,
            idempotency_key=idempotency_key,
            status=ProjectStatus.PENDING,
        )

        db.add(project)
        db.flush()

        # ----------------------------------------------------
        # Deduct Credits
        # ----------------------------------------------------

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

    except Exception:

        db.rollback()

        logger.exception("Upload failed")

        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        raise HTTPException(status_code=400, detail="Invalid or unsupported file")

    # ----------------------------------------------------
    # Trigger Worker
    # ----------------------------------------------------

    background_tasks.add_task(
        enqueue_translation_job,
        project_id,
        s3_key
    )

    logger.info(f"Project {project_id} queued for processing")

    return {
        "message": "Project created",
        "pages": page_count,
        "credits_used": credits_required,
        "remaining_credits": new_balance,
        "project_id": project_id,
    }


# ============================================================
# LIST PROJECTS
# ============================================================

@router.get("/")
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    projects = (
        db.query(TranslationProject)
        .filter(TranslationProject.user_id == current_user.id)
        .order_by(TranslationProject.created_at.desc())
        .limit(50)
        .all()
    )

    return [
        {
            "id": p.id,
            "status": p.status,
            "page_count": p.page_count,
            "credits_used": p.credits_used,
            "created_at": p.created_at
        }
        for p in projects
    ]


# ============================================================
# GET PROJECT STATUS
# ============================================================

@router.get("/{project_id}", response_model=ProjectStatusResponse)
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

    return project


# ============================================================
# DOWNLOAD PROJECT RESULT
# ============================================================

@router.get("/{project_id}/download")
def download_project(
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

    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Project processing not completed yet"
        )

    if not project.output_file:
        raise HTTPException(
            status_code=404,
            detail="Output file not available"
        )

    download_url = generate_presigned_download_url(project.output_file)

    return {
        "download_url": download_url
    }


# ============================================================
# DELETE PROJECT
# ============================================================

@router.delete("/{project_id}")
def delete_project(
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

    db.delete(project)
    db.commit()

    logger.info(f"Project {project_id} deleted")

    return {"message": "Project deleted successfully"}