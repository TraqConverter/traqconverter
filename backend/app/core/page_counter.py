from pypdf import PdfReader
from docx import Document
from PIL import Image
import os


def count_pdf_pages(file_path: str) -> int:
    reader = PdfReader(file_path)
    return len(reader.pages)


def count_docx_pages(file_path: str) -> int:
    # Approximation rule: 500 words = 1 page
    doc = Document(file_path)
    word_count = 0

    for para in doc.paragraphs:
        word_count += len(para.text.split())

    pages = max(1, word_count // 500)
    return pages


def count_image_pages(file_path: str) -> int:
    # Each image = 1 page
    return 1


def get_page_count(file_path: str) -> int:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return count_pdf_pages(file_path)

    if ext == ".docx":
        return count_docx_pages(file_path)

    if ext in [".jpg", ".jpeg", ".png"]:
        return count_image_pages(file_path)

    raise ValueError("Unsupported file type for page counting")