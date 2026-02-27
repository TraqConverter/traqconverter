from sqlalchemy.orm import Session
from app.models.project import TranslationProject, ProjectStatus
from app.database import SessionLocal
import time


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

        project.status = ProjectStatus.PROCESSING
        db.commit()

        time.sleep(2)

        project.status = ProjectStatus.COMPLETED
        db.commit()

        print("[WORKER] Completed")

    except Exception as e:
        print("[WORKER ERROR]", str(e))
        db.rollback()

        if project:
            project.status = ProjectStatus.FAILED
            db.commit()

    finally:
        db.close()