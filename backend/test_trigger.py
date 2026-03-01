import uuid
from app.workers.translation_worker import process_translation_job

project_id = uuid.UUID("119dfe24-8bc4-4d2c-bf93-5bb02c4fcbfd")

process_translation_job(project_id)

print("Worker executed")