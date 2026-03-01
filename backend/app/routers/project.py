import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import TranslationProject, ProjectStatus
from app.models.user import User
from app.models.team import Team
from app.core.file_validation import validate_file_extension, validate_file_size
from app.core.page_counter import get_page_count
from app.services.storage_service import save_file_locally
from app.services.queue_service import enqueue_translation_job
from app.services.credit_service import (
    CreditService,
    WalletNotFoundError,
    InsufficientCreditsError,
)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("/upload")
async def upload_project(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_file_extension(file.filename)
    validate_file_size(file)

    file_path = None
    project = None

    try:
        # 1️⃣ Get user's team
        team = db.query(Team).filter(
            Team.owner_id == current_user.id
        ).first()

        if not team:
            raise HTTPException(status_code=400, detail="Team not found")

        # 2️⃣ Save file
        file_path, _ = save_file_locally(file, str(team.id))

        # 3️⃣ Count pages
        page_count = get_page_count(file_path)
        credits_required = page_count

        # 4️⃣ Create project FIRST (status = PENDING)
        project = TranslationProject(
            user_id=current_user.id,
            file_name=file.filename,
            file_path=file_path,
            page_count=page_count,
            credits_used=credits_required,
            status=ProjectStatus.PENDING,
        )

        db.add(project)
        db.flush()  # 👈 get project.id without committing

        # 5️⃣ Deduct credits (atomic inside same transaction)
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

        # 6️⃣ Commit once
        db.commit()
        db.refresh(project)

        project_id = str(project.id)

    except HTTPException:
        db.rollback()
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise

    except Exception as e:
        db.rollback()
        print("UPLOAD ERROR:", repr(e))  # 👈 TEMP DEBUG
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Invalid or unsupported file")

    # 7️⃣ Trigger worker AFTER commit
    background_tasks.add_task(enqueue_translation_job, project_id)

    return {
        "message": "Project created",
        "pages": page_count,
        "credits_used": credits_required,
        "remaining_credits": new_balance,
        "project_id": project_id,
    }