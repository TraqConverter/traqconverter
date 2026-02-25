import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import TranslationProject
from app.models.user import User
from app.models.team import Team
from app.core.file_validation import validate_file_extension
from app.core.page_counter import get_page_count
from app.services.storage_service import save_file_locally
from app.services.queue_service import enqueue_translation_job
from app.services.job_service import create_translation_job

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("/upload")
async def upload_project(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_file_extension(file.filename)

    try:
        # 1️⃣ Save file
        file_path = save_file_locally(file)

        # 2️⃣ Count pages
        page_count = get_page_count(file_path)

        # 3️⃣ Resolve user's team
        team = db.query(Team).filter(
            Team.owner_id == current_user.id
        ).first()

        if not team:
            raise HTTPException(status_code=400, detail="Team not found")

        # 4️⃣ Create translation job (handles credit deduction internally)
        job = create_translation_job(
            db=db,
            team_id=team.id,
            user_id=current_user.id,
            source_language="AUTO",
            target_language="EN",
            page_count=page_count,
        )

        # 5️⃣ Create project record (linked to user)
        project = TranslationProject(
            user_id=current_user.id,
            file_name=file.filename,
            file_path=file_path,
            page_count=page_count,
            credits_used=page_count,
            status="PROCESSING",
        )

        db.add(project)
        db.commit()
        db.refresh(project)

        # 6️⃣ Queue translation
        enqueue_translation_job(str(project.id))

    except Exception:
        db.rollback()

        if "file_path" in locals() and os.path.exists(file_path):
            os.remove(file_path)

        raise

    return {
        "message": "Project created",
        "pages": page_count,
        "credits_used": page_count,
        "remaining_credits": (
            job.page_count  # optional — adjust if you want actual remaining
        ),
        "project_id": project.id
    }