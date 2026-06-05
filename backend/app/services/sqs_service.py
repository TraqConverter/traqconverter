"""Legacy SQS shim.

The queue is now Postgres-backed (see app.services.queue_service +
app.workers.sqs_worker). This module is kept only so any stale
import of `send_translation_job` doesn't crash — it logs once and
forwards to the Postgres enqueue path.
"""
import logging
from app.services.queue_service import enqueue_translation_job

logger = logging.getLogger(__name__)


def send_translation_job(project_id: str, file_key: str) -> None:
    logger.info(
        "sqs_service.send_translation_job → forwarding to Postgres queue "
        "(project=%s)",
        project_id,
    )
    enqueue_translation_job(project_id, file_key)
