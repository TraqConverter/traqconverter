import boto3
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# SQS CLIENT
# ============================================================

sqs_client = boto3.client(
    "sqs",
    region_name=settings.AWS_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)

QUEUE_URL = settings.SQS_QUEUE_URL


# ============================================================
# SEND TRANSLATION JOB
# ============================================================

def send_translation_job(project_id: str):

    message = {
        "project_id": project_id
    }

    try:
        response = sqs_client.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(message)
        )

        logger.info(f"SQS job sent for project {project_id}")

        return response

    except Exception:
        logger.exception("Failed sending SQS job")
        raise