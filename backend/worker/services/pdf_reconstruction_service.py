from pdf2image import convert_from_path
from reportlab.pdfgen import canvas
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# --------------------------------------------------
# Poppler binary location (Windows)
# --------------------------------------------------

POPPLER_PATH = r"C:\poppler\poppler-25.12.0\Library\bin"


def build_searchable_pdf(input_pdf, translated_lines):

    logger.info("Generating searchable PDF")

    images = convert_from_path(
        input_pdf,
        poppler_path=POPPLER_PATH
    )

    output_path = Path(input_pdf).parent / "translated_searchable.pdf"

    c = canvas.Canvas(str(output_path))

    line_index = 0

    for page in images:

        width, height = page.size

        c.drawInlineImage(page, 0, 0, width=width, height=height)

        y = height - 40

        while line_index < len(translated_lines):

            text = translated_lines[line_index]

            c.drawString(40, y, text)

            y -= 20
            line_index += 1

            if y < 40:
                break

        c.showPage()

    c.save()

    logger.info("Searchable PDF generated")

    return output_path