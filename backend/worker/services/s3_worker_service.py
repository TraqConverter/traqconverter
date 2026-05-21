import boto3
import logging
from pathlib import Path
from app.config import settings

logger = logging.getLogger(__name__)

s3 = boto3.client(
    "s3",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_REGION
)

BUCKET = settings.S3_BUCKET_NAME


def download_file(key: str, destination: Path):

    s3.download_file(
        BUCKET,
        key,
        str(destination)
    )

    logger.info(f"Downloaded {key} from S3")


def upload_file(local_path: Path, key: str):

    s3.upload_file(
        str(local_path),
        BUCKET,
        key
    )

    logger.info(f"Uploaded processed file {key}")