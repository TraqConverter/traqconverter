from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import SessionLocal
from app.models.project import TranslationProject, ProjectStatus

MAX_ATTEMPTS = 3
STALL_TIMEOUT_MINUTES = 2


def recover_stalled_jobs():
    print("[WATCHDOG] Checking for stalled jobs...")

    db: Session = SessionLocal()

    try:
        timeout_threshold = datetime.utcnow() - timedelta(
            minutes=STALL_TIMEOUT_MINUTES
        )

        stalled_projects = db.query(TranslationProject).filter(
            TranslationProject.status == ProjectStatus.PROCESSING,
            or_(
                TranslationProject.last_heartbeat == None,
                TranslationProject.last_heartbeat < timeout_threshold
            )
        ).all()

        print(f"[WATCHDOG] Found {len(stalled_projects)} stalled jobs")

        for project in stalled_projects:
            print(f"[WATCHDOG] Recovering project {project.id}")

            if project.retry_count >= MAX_ATTEMPTS:
                project.status = ProjectStatus.FAILED
                print("[WATCHDOG] Marked FAILED")
            else:
                project.status = ProjectStatus.PENDING
                print("[WATCHDOG] Returned to PENDING")

        db.commit()

    except Exception as e:
        db.rollback()
        print("[WATCHDOG ERROR]", str(e))

    finally:
        db.close()