import logging
from pathlib import Path
from pypdf import PdfReader

logger = logging.getLogger(__name__)


# =========================================
# EXTRACT PARAGRAPHS FROM PDF
# =========================================
def extract_paragraphs(file_path: Path):

    reader = PdfReader(file_path)

    paragraphs = []
    seen = set()

    for page in reader.pages:

        text = page.extract_text()

        if not text:
            continue

        lines = text.split("\n")

        for line in lines:

            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            # Normalize whitespace
            line = " ".join(line.split())

            # Skip very short garbage segments
            if len(line) < 2:
                continue

            # Prevent duplicates (common with PDF headers/footers)
            if line in seen:
                continue

            seen.add(line)

            paragraphs.append(line)

    logger.info(f"Extracted {len(paragraphs)} segments")

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