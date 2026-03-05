import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def process_translation(file_path: Path) -> Path:

    logger.info(f"Processing translation for {file_path}")

    output = file_path.with_name("translated_" + file_path.name)

    # TEMP placeholder
    # later this is where translation engine runs

    with open(file_path, "rb") as f:
        data = f.read()

    with open(output, "wb") as f:
        f.write(data)

    return output

from pypdf import PdfReader


def extract_paragraphs(file_path):

    reader = PdfReader(file_path)

    paragraphs = []

    for page in reader.pages:

        text = page.extract_text()

        if not text:
            continue

        lines = text.split("\n")

        for line in lines:

            line = line.strip()

            if line:
                paragraphs.append(line)

    return paragraphs