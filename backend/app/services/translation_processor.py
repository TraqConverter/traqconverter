from sqlalchemy.orm import Session
from app.models.project import TranslationProject, ProjectStatus
from app.database import SessionLocal
from datetime import datetime, timedelta
import time

MAX_ATTEMPTS = 3


def process_translation_job(project_id: str):
    print(f"[WORKER] Starting processing for {project_id}")

    db: Session = SessionLocal()

    try:
        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_id
        ).first()

        if not project:
            print("[WORKER] Project not found")
            return

        print("[WORKER] Project found")

        # ----------------------------------------------------
        # Crash Recovery Detection
        # ----------------------------------------------------
        if (
            project.status == ProjectStatus.PROCESSING
            and project.last_heartbeat
            and datetime.utcnow() - project.last_heartbeat > timedelta(seconds=60)
        ):
            print("[WORKER] Detected stale PROCESSING job. Resetting to PENDING.")
            project.status = ProjectStatus.PENDING
            db.commit()

        # ----------------------------------------------------
        # Completed Guard
        # ----------------------------------------------------
        if project.status == ProjectStatus.COMPLETED:
            print("[WORKER] Already completed")
            return

        # ----------------------------------------------------
        # Retry Limit Guard
        # ----------------------------------------------------
        if project.retry_count >= MAX_ATTEMPTS:
            print("[WORKER] Max attempts reached. Marking FAILED.")
            project.status = ProjectStatus.FAILED
            db.commit()
            return

        # ----------------------------------------------------
        # Begin Processing
        # ----------------------------------------------------
        project.retry_count += 1
        project.last_heartbeat = datetime.utcnow()
        project.status = ProjectStatus.PROCESSING
        project.progress_percent = 0
        db.commit()

        print(f"[WORKER] Attempt #{project.retry_count}")

        # ----------------------------------------------------
        # Simulated Long Processing With Progress + Heartbeat
        # ----------------------------------------------------
        total_steps = 4

        for i in range(total_steps):
            time.sleep(1)

            project.progress_percent = int(((i + 1) / total_steps) * 100)
            project.last_heartbeat = datetime.utcnow()
            db.commit()

            print(f"[WORKER] Progress: {project.progress_percent}%")

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------
        project.status = ProjectStatus.COMPLETED
        project.progress_percent = 100
        project.last_heartbeat = datetime.utcnow()
        db.commit()

        print("[WORKER] Completed")

    except Exception as e:
        print("[WORKER ERROR]", str(e))
        db.rollback()

        project = db.query(TranslationProject).filter(
            TranslationProject.id == project_id
        ).first()

        if project:
            if project.retry_count >= MAX_ATTEMPTS:
                project.status = ProjectStatus.FAILED
                print("[WORKER] Permanently FAILED")
            else:
                project.status = ProjectStatus.PENDING
                print("[WORKER] Marked PENDING for queue retry")

            db.commit()

    finally:
        db.close()


def recover_stalled_jobs():
    print("[WATCHDOG] Checking for stalled jobs...")

    db: Session = SessionLocal()

    try:
        timeout_threshold = datetime.utcnow() - timedelta(minutes=2)

        stalled_projects = db.query(TranslationProject).filter(
            TranslationProject.status == ProjectStatus.PROCESSING,
            TranslationProject.last_heartbeat < timeout_threshold
        ).all()

        print(f"[WATCHDOG] Found {len(stalled_projects)} stalled jobs")

        for project in stalled_projects:
            print(f"[WATCHDOG] Recovering {project.id}")

            if project.retry_count >= MAX_ATTEMPTS:
                project.status = ProjectStatus.FAILED
                print("[WATCHDOG] Marked FAILED")
            else:
                project.status = ProjectStatus.PENDING
                print("[WATCHDOG] Returned to PENDING")

        db.commit()

    finally:
        db.close()