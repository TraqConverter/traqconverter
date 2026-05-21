import boto3
import uuid
import logging
from pathlib import Path
from botocore.exceptions import ClientError
from botocore.config import Config

from app.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# S3 CLIENT (IAM compatible)
# ----------------------------------------------------------------
# Audit medium fix: explicit retries (3 with adaptive backoff) and
# socket timeouts so a slow S3 endpoint can't hang a translation job.
# ============================================================

_s3_config = Config(
    region_name=settings.AWS_REGION,
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=10,
    read_timeout=60,
)

s3_client = boto3.client("s3", config=_s3_config)

BUCKET_NAME = settings.S3_BUCKET_NAME


# ============================================================
# Upload File
# ============================================================

def upload_file_to_s3(file_path: Path) -> str:
    """
    Upload a file to S3 and return the object key.
    """

    key = f"uploads/{uuid.uuid4()}_{file_path.name}"

    try:

        s3_client.upload_file(
            str(file_path),
            BUCKET_NAME,
            key,
            ExtraArgs={
                "ServerSideEncryption": "AES256"
            }
        )

        logger.info(f"S3 upload successful: {key}")

        return key

    except ClientError:

        logger.exception("S3 upload failed")

        raise


# ============================================================
# Download File
# ============================================================

def download_file_from_s3(key: str, destination: Path):
    """
    Download a file from S3 to local worker storage.
    """

    try:

        s3_client.download_file(
            BUCKET_NAME,
            key,
            str(destination)
        )

        logger.info(f"S3 download successful: {key}")

    except ClientError:

        logger.exception("S3 download failed")

        raise


# ============================================================
# Generate Signed Download URL
# ============================================================

def generate_presigned_download_url(key: str, expiration: int = 3600) -> str:
    """
    Generate a temporary secure download URL.
    """

    try:

        url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": key
            },
            ExpiresIn=expiration
        )

        logger.info(f"Generated signed URL for {key}")

        return url

    except ClientError:

        logger.exception("Failed generating signed URL")

        raise