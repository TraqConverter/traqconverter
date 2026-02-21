import os
import shutil
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import TranslationProject
from app.models.user import User
from app.core.file_validation import validate_file_extension
from app.core.page_counter import get_page_count

router = APIRouter(prefix="/projects", tags=["Projects"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload")
async def upload_project(
    file: UploadFile = File(...),
    quote_request: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate extension
    validate_file_extension(file.filename)

    # Save file
    file_id = str(uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{file_id}_{file.filename}")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Count pages
    page_count = get_page_count(file_path)
    credits_required = page_count

    # Deduct credits if not quote request
    if not quote_request:
        if current_user.monthly_credits < credits_required:
            raise HTTPException(
                status_code=400,
                detail="Insufficient credits"
            )

        current_user.monthly_credits -= credits_required
        db.add(current_user)

    # Create project
    project = TranslationProject(
        user_id=current_user.id,
        file_name=file.filename,
        file_path=file_path,
        page_count=page_count,
        credits_used=0 if quote_request else credits_required,
        status="QUOTE_REQUESTED" if quote_request else "IN_PROGRESS",
        is_quote_request=quote_request,
    )

    db.add(project)
    db.commit()
    db.refresh(current_user)

    return {
        "message": "Project created",
        "pages": page_count,
        "credits_used": 0 if quote_request else credits_required,
    }