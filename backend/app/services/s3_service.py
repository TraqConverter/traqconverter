"""Object storage service.

Backed by Supabase Storage in production via Supabase's S3-compatible
API, but the same code path also works with real AWS S3 (or any
S3-API-compatible endpoint such as MinIO, Cloudflare R2, Wasabi)
because we use plain boto3 under the hood.

Backend selection is purely env-driven:

    SUPABASE_S3_ENDPOINT     set → use Supabase Storage
                             (e.g. https://<project>.supabase.co/storage/v1/s3)
    SUPABASE_S3_ACCESS_KEY     Supabase dashboard → Project Settings →
    SUPABASE_S3_SECRET_KEY     Storage → S3 access keys.
    SUPABASE_S3_REGION         default 'us-east-1' (Supabase accepts any).

If `SUPABASE_S3_ENDPOINT` is not set we fall back to standard AWS S3
(the original behaviour), so existing deployments keep working
without a migration.

The bucket name comes from `S3_BUCKET_NAME` in either case.
"""
import boto3
import uuid
import logging
from pathlib import Path
from botocore.exceptions import ClientError
from botocore.config import Config

from app.config import settings

logger = logging.getLogger(__name__)


def _build_s3_client():
    """Return a boto3 client pointed at Supabase Storage when its env
    vars are set, otherwise at AWS S3."""
    cfg = Config(
        region_name=(
            getattr(settings, "SUPABASE_S3_REGION", None)
            or settings.AWS_REGION
            or "us-east-1"
        ),
        retries={"max_attempts": 3, "mode": "adaptive"},
        connect_timeout=10,
        read_timeout=60,
        # Supabase requires path-style addressing; AWS supports both.
        s3={"addressing_style": "path"},
        signature_version="s3v4",
    )

    supabase_endpoint = getattr(settings, "SUPABASE_S3_ENDPOINT", None)
    if supabase_endpoint:
        logger.info("Storage backend: Supabase Storage (S3-compatible)")
        return boto3.client(
            "s3",
            endpoint_url=supabase_endpoint,
            aws_access_key_id=getattr(
                settings, "SUPABASE_S3_ACCESS_KEY", None
            ),
            aws_secret_access_key=getattr(
                settings, "SUPABASE_S3_SECRET_KEY", None
            ),
            config=cfg,
        )

    # Fall back to real AWS S3. Credentials come from the default
    # boto3 chain (env vars → ~/.aws/credentials → IAM role) unless
    # explicit keys are configured.
    logger.info("Storage backend: AWS S3")
    kwargs = {"config": cfg}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


s3_client = _build_s3_client()

BUCKET_NAME = settings.S3_BUCKET_NAME


# ============================================================
# Upload File
# ============================================================

def upload_file_to_s3(file_path: Path) -> str:
    """Upload a file and return the object key."""
    key = f"uploads/{uuid.uuid4()}_{file_path.name}"

    try:
        # Supabase doesn't accept ServerSideEncryption headers, so we
        # only send them when we're actually talking to real AWS S3.
        extra_args: dict = {}
        if not getattr(settings, "SUPABASE_S3_ENDPOINT", None):
            extra_args["ServerSideEncryption"] = "AES256"

        s3_client.upload_file(
            str(file_path),
            BUCKET_NAME,
            key,
            ExtraArgs=extra_args or None,
        )
        logger.info(f"Object upload successful: {key}")
        return key
    except ClientError:
        logger.exception("Object upload failed")
        raise


# ============================================================
# Download File
# ============================================================

def download_file_from_s3(key: str, destination: Path):
    """Download an object to local filesystem."""
    try:
        s3_client.download_file(BUCKET_NAME, key, str(destination))
        logger.info(f"Object download successful: {key}")
    except ClientError:
        logger.exception("Object download failed")
        raise


# ============================================================
# Generate Signed Download URL
# ============================================================

def generate_presigned_download_url(key: str, expiration: int = 3600) -> str:
    """Generate a temporary secure download URL.

    Supabase Storage's S3 endpoint supports get_object presigned URLs
    out of the box — same code path as AWS.
    """
    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": key},
            ExpiresIn=expiration,
        )
        logger.info(f"Generated signed URL for {key}")
        return url
    except ClientError:
        logger.exception("Failed generating signed URL")
        raise
