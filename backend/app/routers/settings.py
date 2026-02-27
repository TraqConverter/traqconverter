from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.core.file_validation import validate_file_extension, validate_file_size
from app.services.storage_service import save_certification_file

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.post("/upload-certification")
async def upload_certification(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_file_extension(file.filename)
    validate_file_size(file)

    file_path = None

    try:
        file_path = save_certification_file(file, str(current_user.id))

        current_user.certification_file = file_path
        db.commit()

        return {
            "message": "Certification uploaded successfully",
            "file_path": file_path
        }

    except Exception:
        db.rollback()

        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        raise HTTPException(
            status_code=400,
            detail="Certification upload failed"
        )