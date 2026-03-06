import logging
from pathlib import Path
from pypdf import PdfReader

logger = logging.getLogger(__name__)


# =========================================
# EXTRACT PARAGRAPHS FROM PDF
# =========================================
from pypdf import PdfReader
from worker.services.ocr_service import extract_text_with_textract


def extract_paragraphs(file_path):

    reader = PdfReader(file_path)

    paragraphs = []

    for page in reader.pages:

        text = page.extract_text()

        if text:
            lines = text.split("\n")

            for line in lines:
                line = line.strip()
                if line:
                    paragraphs.append(line)

    # --------------------------------
    # If no text found → use OCR
    # --------------------------------

    if not paragraphs:

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        paragraphs = extract_text_with_textract(file_bytes)

    return paragraphs


# =========================================
# TRANSLATION PROCESSOR (TEMP PLACEHOLDER)
# =========================================
def process_translation(file_path: Path) -> Path:

    logger.info(f"Processing translation for {file_path}")

    output = file_path.with_name("translated_" + file_path.name)

    # -------------------------------------
    # TEMP placeholder
    # later this is where translation runs
    # -------------------------------------

    with open(file_path, "rb") as f:
        data = f.read()

    with open(output, "wb") as f:
        f.write(data)

    return output