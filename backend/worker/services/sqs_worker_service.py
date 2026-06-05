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


def receive_job():

    response = sqs.receive_message(
        QueueUrl=QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=10
    )

    messages = response.get("Messages", [])

    if not messages:
        return None

    message = messages[0]

    body = json.loads(message["Body"])
    receipt_handle = message["ReceiptHandle"]

    return body, receipt_handle


def delete_job(receipt_handle):

    sqs.delete_message(
        QueueUrl=QUEUE_URL,
        ReceiptHandle=receipt_handle
    )