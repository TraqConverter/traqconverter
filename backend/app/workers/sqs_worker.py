import json
import boto3
import time
import logging
import threading

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

# MUST be > max processing time (set this properly)
VISIBILITY_TIMEOUT = 300  # 5 minutes
HEARTBEAT_INTERVAL = 60   # extend every 60 seconds


# ============================================================
# VISIBILITY HEARTBEAT (prevents duplicate processing)
# ============================================================
def start_visibility_heartbeat(receipt_handle: str, stop_event: threading.Event):
    while not stop_event.is_set():
        try:
            time.sleep(HEARTBEAT_INTERVAL)

            sqs.change_message_visibility(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=VISIBILITY_TIMEOUT
            )

            logger.info("🔄 Visibility extended")

        except Exception as e:
            logger.warning(f"Heartbeat failed: {e}")


# ============================================================
# WORKER LOOP
# ============================================================
def start_worker():
    logger.info("Worker started")
    logger.info(f"Using queue: {QUEUE_URL}")

    while True:
        try:
            logger.info("⏳ Polling SQS...")

            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=VISIBILITY_TIMEOUT  # ✅ FIX
            )

            messages = response.get("Messages", [])

            if not messages:
                continue

            message = messages[0]
            receipt_handle = message["ReceiptHandle"]

            body = json.loads(message["Body"])

            # 🔥 SNS unwrap support
            if isinstance(body, str):
                body = json.loads(body)

            project_id = body.get("project_id")

            if not project_id:
                logger.warning(f"⚠️ Invalid message: {body}")
                continue

            logger.info(f"📥 Processing project: {project_id}")

            # ============================================================
            # START HEARTBEAT THREAD
            # ============================================================
            stop_event = threading.Event()
            heartbeat_thread = threading.Thread(
                target=start_visibility_heartbeat,
                args=(receipt_handle, stop_event),
                daemon=True
            )
            heartbeat_thread.start()

            try:
                # 🔥 PROCESS JOB
                process_translation_job(project_id)

                # ✅ SUCCESS → DELETE MESSAGE
                sqs.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=receipt_handle
                )

                logger.info(f"✅ Completed project: {project_id}")

            finally:
                # 🔥 STOP HEARTBEAT
                stop_event.set()

        except Exception as e:
            logger.error(f"❌ Worker failed: {str(e)}")

        time.sleep(1)


if __name__ == "__main__":
    start_worker()