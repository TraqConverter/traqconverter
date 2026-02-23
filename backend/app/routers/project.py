import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import TranslationProject
from app.models.user import User
from app.core.file_validation import validate_file_extension
from app.core.page_counter import get_page_count
from app.services.credit_service import deduct_user_credits
from app.services.storage_service import save_file_locally
from app.services.queue_service import enqueue_translation_job  

@router.post("/upload")
async def upload_project(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_file_extension(file.filename)

    try:
        # 1️⃣ Save file via storage service
        file_path = save_file_locally(file)

        # 2️⃣ Count pages
        page_count = get_page_count(file_path)
        credits_required = page_count

        # 3️⃣ Deduct credits (row locked in service)
        new_balance = deduct_user_credits(
            db=db,
            user_id=current_user.id,
            pages=credits_required
        )

        # 4️⃣ Create project record
        project = TranslationProject(
            user_id=current_user.id,
            file_name=file.filename,
            file_path=file_path,
            page_count=page_count,
            credits_used=credits_required,
            status="PROCESSING",
        )

        db.add(project)
        db.commit()
        db.refresh(project)

        # 5️⃣ Queue translation job (after successful commit)
        enqueue_translation_job(str(project.id))

    except Exception:
        db.rollback()

        if "file_path" in locals() and os.path.exists(file_path):
            os.remove(file_path)

        raise

    return {
        "message": "Project created",
        "pages": page_count,
        "credits_used": credits_required,
        "remaining_credits": new_balance,
        "project_id": project.id
    }