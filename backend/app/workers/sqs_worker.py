import json
import boto3
import time
import logging

from app.services.translation_processor import process_translation_job
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sqs = boto3.client(
    "sqs",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_REGION
)

QUEUE_URL = settings.SQS_QUEUE_URL


def start_worker():
    print("🚀 Worker started")
    print("Using queue:", QUEUE_URL)

    while True:
        try:
            print("⏳ Polling SQS...")

            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20  # long polling
            )

            messages = response.get("Messages", [])

            if not messages:
                continue

            message = messages[0]

            body = json.loads(message["Body"])

            # 🔥 handle SNS-style wrapping (important)
            if isinstance(body, str):
                body = json.loads(body)

            project_id = body.get("project_id")

            if not project_id:
                print("⚠️ Invalid message:", body)
                continue

            print(f"📥 Processing project: {project_id}")

            # 🔥 PROCESS JOB
            process_translation_job(project_id)

            # ✅ delete after success
            sqs.delete_message(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=message["ReceiptHandle"]
            )

            print(f"✅ Completed project: {project_id}")

        except Exception as e:
            logger.error(f"❌ Worker failed: {str(e)}")

        time.sleep(1)


if __name__ == "__main__":
    start_worker()