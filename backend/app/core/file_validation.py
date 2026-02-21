ALLOWED_EXTENSIONS = {".pdf", ".docx", ".jpg", ".jpeg", ".png"}
DISALLOWED_EXTENSIONS = {".txt", ".rtf", ".html", ".htm"}


def validate_file_extension(filename: str):
    import os

    ext = os.path.splitext(filename)[1].lower()

    if ext in DISALLOWED_EXTENSIONS:
        raise ValueError("This file type is not supported for credit-based billing.")

    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type.")

    return ext