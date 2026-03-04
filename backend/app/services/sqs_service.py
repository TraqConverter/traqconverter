import boto3
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

sqs = boto3.client(
    "sqs",
    aws_access_key_id=settings.AWS_ACCESS_KEY,
    aws_secret_access_key=settings.AWS_SECRET_KEY,
    region_name=settings.AWS_REGION,
)

QUEUE_URL = settings.SQS_QUEUE_URL


def send_translation_job(project_id: str):

    message = {
        "project_id": project_id
    }

    response = sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(message)
    )

    logger.info(f"SQS message sent for project {project_id}")

    return response