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

# ============================================================
# CONFIG
# ============================================================
# Must exceed worst-case processing time
VISIBILITY_TIMEOUT = 300  # 5 minutes
HEARTBEAT_INTERVAL = 60   # extend every 60 seconds


# ============================================================
# VISIBILITY HEARTBEAT
# Prevents duplicate processing for long jobs
# ============================================================
def start_visibility_heartbeat(
    receipt_handle: str,
    stop_event: threading.Event
):
    while not stop_event.is_set():
        try:
            time.sleep(HEARTBEAT_INTERVAL)

            # Stop immediately if worker already finished
            if stop_event.is_set():
                break

            sqs.change_message_visibility(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=VISIBILITY_TIMEOUT
            )

            logger.info("🔄 Visibility extended")

        except Exception as e:
            # Message may already be deleted / invalid
            logger.warning(f"Heartbeat failed: {e}")

            # Stop heartbeat if receipt handle is invalid
            break


# ============================================================
# MESSAGE PARSING
# Handles:
# - direct JSON
# - SNS-wrapped JSON
# ============================================================
def parse_message_body(raw_body: str) -> dict:
    body = json.loads(raw_body)

    # SNS wrapper
    if isinstance(body, dict) and "Message" in body:
        body = json.loads(body["Message"])

    # Double-encoded edge case
    elif isinstance(body, str):
        body = json.loads(body)

    return body


# ============================================================
# WORKER LOOP
# ============================================================
def start_worker():
    logger.info("🚀 Worker started")
    logger.info(f"Using queue: {QUEUE_URL}")

    while True:
        try:
            logger.info("⏳ Polling SQS...")

            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=VISIBILITY_TIMEOUT,
            )

            messages = response.get("Messages", [])

            if not messages:
                continue

            message = messages[0]
            receipt_handle = message["ReceiptHandle"]

            # ====================================================
            # PARSE MESSAGE
            # ====================================================
            try:
                body = parse_message_body(message["Body"])

            except Exception:
                logger.exception("❌ Failed to parse SQS message body")

                # Delete poison message
                sqs.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=receipt_handle
                )

                continue

            project_id = body.get("project_id")

            if not project_id:
                logger.warning(f"⚠️ Invalid message: {body}")

                # Delete malformed message
                sqs.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=receipt_handle
                )

                continue

            logger.info(f"📥 Processing project: {project_id}")

            # ====================================================
            # START HEARTBEAT
            # ====================================================
            stop_event = threading.Event()

            heartbeat_thread = threading.Thread(
                target=start_visibility_heartbeat,
                args=(receipt_handle, stop_event),
                daemon=True
            )

            heartbeat_thread.start()

            # ====================================================
            # PROCESS JOB
            # ====================================================
            success = False

            try:
                process_translation_job(project_id)
                success = True

            except Exception:
                logger.exception(
                    f"❌ Worker failed for project: {project_id}"
                )

            finally:
                # Always stop heartbeat
                stop_event.set()

            # ====================================================
            # DELETE ONLY ON SUCCESS
            # ====================================================
            if success:
                try:
                    sqs.delete_message(
                        QueueUrl=QUEUE_URL,
                        ReceiptHandle=receipt_handle
                    )

                    logger.info(
                        f"✅ Completed project: {project_id}"
                    )

                except Exception:
                    logger.exception(
                        f"❌ Failed deleting SQS message for {project_id}"
                    )

            else:
                # Leave message for retry / watchdog
                logger.warning(
                    f"⚠️ Job failed, message retained for retry: {project_id}"
                )

        except Exception:
            logger.exception("❌ Worker loop failed")

        time.sleep(1)


if __name__ == "__main__":
    start_worker()