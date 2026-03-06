import boto3
import logging

from app.config import settings

logger = logging.getLogger(__name__)

textract = boto3.client(
    "textract",
    region_name=settings.AWS_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)


def extract_text_with_textract(file_bytes):

    response = textract.detect_document_text(
        Document={"Bytes": file_bytes}
    )

    lines = []

    for block in response["Blocks"]:

        if block["BlockType"] == "LINE":
            lines.append(block["Text"])

    logger.info(f"OCR extracted {len(lines)} lines")

    return lines