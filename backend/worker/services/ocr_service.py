import boto3
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# --------------------------------------------------
# STEP 1 — OCR Confidence Threshold
# --------------------------------------------------

CONFIDENCE_THRESHOLD = 80.0

textract = boto3.client(
    "textract",
    region_name=os.getenv("AWS_REGION", "us-east-1")
)


def extract_text_with_textract(file_path):
    """
    Extract text from scanned PDFs using AWS Textract.
    Returns a list of text lines for segmentation.
    """

    logger.info("Running Textract OCR")

    with open(file_path, "rb") as document:
        image_bytes = document.read()

    response = textract.detect_document_text(
        Document={"Bytes": image_bytes}
    )

    lines = []

    for block in response["Blocks"]:

        if block["BlockType"] != "LINE":
            continue

        # --------------------------------------------
        # STEP 1 — Confidence filtering
        # --------------------------------------------

        confidence = block.get("Confidence", 0)

        if confidence < CONFIDENCE_THRESHOLD:
            logger.warning(
                f"OCR line skipped due to low confidence ({confidence:.2f}%)"
            )
            continue

        text = block["Text"].strip()

        if text:
            lines.append(text)

    # --------------------------------------------------
    # STEP 2 — OCR Failure Handling
    # --------------------------------------------------

    if not lines:
        logger.error("OCR extraction failed — no usable text detected")
        raise Exception("Textract OCR produced no usable text")

    logger.info(f"OCR extracted {len(lines)} lines")

    return lines