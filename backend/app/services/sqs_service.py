import boto3
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

sqs = boto3.client(
    "sqs",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_REGION
)

QUEUE_URL = settings.SQS_QUEUE_URL


def send_translation_job(project_id: str, file_key: str):

    message = {
        "project_id": project_id,
        "file_key": file_key
    }

    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(message)
    )

    logger.info(f"SQS job sent for project {project_id}")