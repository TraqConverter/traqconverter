from docx import Document
from PIL import Image
from fastapi import HTTPException
import os





MAX_PAGES = int(os.getenv("MAX_UPLOAD_PAGES", "100"))


def count_pdf_pages(file_path: str) -> int:
    import fitz

    try:
        doc = fitz.open(file_path)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or unsupported PDF file")
    try:
        # Owner-password-only PDFs open fine; only a user password blocks reading.
        if doc.needs_pass:
            raise HTTPException(status_code=400, detail="Password-protected PDFs are not supported")
        page_count = doc.page_count
    finally:
        doc.close()
    if page_count <= 0:
        raise HTTPException(status_code=400, detail="Invalid PDF file")
    return page_count


def count_docx_pages(file_path: str) -> int:
    try:
        doc = Document(file_path)
        from docx.oxml.ns import qn

        # Includes table cells and text boxes, not just top-level paragraphs.
        word_count = sum(len((t.text or "").split()) for t in doc.element.body.iter(qn("w:t")))

        pages = max(1, (word_count + 499) // 500)

        return pages

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid or unsupported DOCX file"
        )





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





def get_page_count(file_path: str) -> int:
    pages = _count_pages(file_path)
    if pages > MAX_PAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Documents are limited to {MAX_PAGES} pages; split larger files",
        )
    return pages


def _count_pages(file_path: str) -> int:
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