from pypdf import PdfReader
from docx import Document
from PIL import Image
from fastapi import HTTPException
import os


# ---------------------------------------------------
# PDF
# ---------------------------------------------------
def count_pdf_pages(file_path: str) -> int:
    try:
        reader = PdfReader(file_path)

        if reader.is_encrypted:
            raise HTTPException(
                status_code=400,
                detail="Encrypted PDFs are not supported"
            )

        page_count = len(reader.pages)

        if page_count <= 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid PDF file"
            )

        return page_count

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid or unsupported PDF file"
        )


# ---------------------------------------------------
# DOCX (Word count approximation)
# ---------------------------------------------------
def count_docx_pages(file_path: str) -> int:
    try:
        doc = Document(file_path)
        word_count = 0

        for para in doc.paragraphs:
            word_count += len(para.text.split())

        pages = max(1, (word_count + 499) // 500)

        return pages

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid or unsupported DOCX file"
        )


# ---------------------------------------------------
# Image
# ---------------------------------------------------
def count_image_pages(file_path: str) -> int:
    try:
        with Image.open(file_path) as img:
            img.verify()
        return 1
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid or corrupted image file"
        )


# ---------------------------------------------------
# Dispatcher
# ---------------------------------------------------
def get_page_count(file_path: str) -> int:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return count_pdf_pages(file_path)

    if ext == ".docx":
        return count_docx_pages(file_path)

    if ext in [".jpg", ".jpeg", ".png"]:
        return count_image_pages(file_path)

    raise HTTPException(
        status_code=400,
        detail="Unsupported file type"
    )