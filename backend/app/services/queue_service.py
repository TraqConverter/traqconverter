import logging
from app.services.sqs_service import send_translation_job

logger = logging.getLogger(__name__)


def enqueue_translation_job(project_id: str):
    logger.info(f"Sending project {project_id} to SQS")
    send_translation_job(project_id)