import os
from fastapi import HTTPException

ALLOWED_EXTENSIONS = [".pdf", ".docx", ".jpg", ".jpeg", ".png"]
MAX_FILE_SIZE_MB = 20


def validate_file_extension(filename: str):
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}"
        )


def validate_file_size(file):
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)

    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

    if size > max_bytes:
        raise HTTPException(
            status_code=400,
            detail="File too large"
        )