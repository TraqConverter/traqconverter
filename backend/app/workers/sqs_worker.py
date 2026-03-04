import json
import boto3
import time
import logging
from app.services.translation_processor import process_translation_job
from app.config import settings

logger = logging.getLogger(__name__)

sqs = boto3.client(
    "sqs",
    aws_access_key_id=settings.AWS_ACCESS_KEY,
    aws_secret_access_key=settings.AWS_SECRET_KEY,
    region_name=settings.AWS_REGION
)

QUEUE_URL = settings.SQS_QUEUE_URL


def start_worker():
    print("Worker using queue:", QUEUE_URL)
    print("SQS worker started...")

    while True:
        print("Polling SQS...")

        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20
        )

        print("SQS RESPONSE:", response)

        messages = response.get("Messages", [])

        if not messages:
            continue

        message = messages[0]

        body = json.loads(message["Body"])

        if isinstance(body, str):
            body = json.loads(body)

        project_id = body["project_id"]

        print("Processing project:", project_id)

        try:
            process_translation_job(project_id)

            sqs.delete_message(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=message["ReceiptHandle"]
            )

            print("Message deleted from queue")

        except Exception as e:
            logger.error("Worker failed:", e)

        time.sleep(1)