import os
import re
from pathlib import Path

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


MAX_FILE_NAME_LENGTH = 200
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def local_file_name(file_name: str | None) -> str:
    """The file name made safe to join to a local dir: no folders, no absolute paths, no '..'."""
    name = Path((file_name or "").replace("\\", "/")).name.strip()
    return name if name and name not in (".", "..") else "source" + Path(file_name or "").suffix.lower()


def clean_file_name(name: str | None) -> str:
    """A project's display name: no path separators or control characters, capped in length, extension kept."""
    cleaned = _CONTROL_CHARS.sub("", (name or "").replace("/", "-").replace("\\", "-"))
    cleaned = " ".join(cleaned.split()).strip(" .")
    if len(cleaned) > MAX_FILE_NAME_LENGTH:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            cleaned = stem[: MAX_FILE_NAME_LENGTH - len(ext) - 1].rstrip() + "." + ext
        else:
            cleaned = cleaned[:MAX_FILE_NAME_LENGTH].rstrip()
    return cleaned