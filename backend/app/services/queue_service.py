from app.services.translation_processor import process_translation_job


def enqueue_translation_job(project_id: str):
    print(f"[QUEUE] Translation job queued for project {project_id}")

    # DEV mode: process immediately
    process_translation_job(project_id)