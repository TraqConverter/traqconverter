from pathlib import Path
import shutil
import tempfile
import traceback
import uuid

from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.models.project import TranslationProject, ProjectStatus
from app.services.certification_service import CertificationService
from app.services.pdf_merge_service import PdfMergeService


# ============================================================
# PUBLIC ENTRYPOINT (DEV MODE)
# ============================================================

def enqueue_translation_job(project_id: uuid.UUID):
    """
    Called via FastAPI BackgroundTasks AFTER commit.
    """
    process_translation_job(project_id)


# ============================================================
# CORE WORKER
# ============================================================

def process_translation_job(project_id: uuid.UUID) -> None:

    db = SessionLocal()

    try:
        project = (
            db.query(TranslationProject)
            .options(joinedload(TranslationProject.user))
            .filter(TranslationProject.id == project_id)
            .first()
        )

        if not project:
            return

        if project.status != ProjectStatus.PENDING:
            return

        # ----------------------------------------------------
        # Move to PROCESSING
        # ----------------------------------------------------
        project.status = ProjectStatus.PROCESSING
        db.commit()
        db.refresh(project)

        # ----------------------------------------------------
        # Generate translated output
        # ----------------------------------------------------
        output_path = _generate_translation_output(project)

        # ----------------------------------------------------
        # Certification Injection (BEFORE persistence)
        # ----------------------------------------------------
        if project.add_certification:
            _inject_certification(project, output_path)

        # ----------------------------------------------------
        # Persist final state atomically
        # ----------------------------------------------------
        project.output_file = str(output_path)
        project.status = ProjectStatus.COMPLETED

        db.commit()

    except Exception:
        db.rollback()

        try:
            failed_project = (
                db.query(TranslationProject)
                .filter(TranslationProject.id == project_id)
                .first()
            )

            if failed_project:
                failed_project.status = ProjectStatus.FAILED
                db.commit()

        except SQLAlchemyError:
            db.rollback()

        print("Translation worker failed:")
        print(traceback.format_exc())

    finally:
        db.close()


# ============================================================
# TRANSLATION GENERATION (SIMULATION)
# ============================================================

def _generate_translation_output(project: TranslationProject) -> Path:
    """
    Replace this with real translation engine later.
    Currently performs a safe copy.
    """

    original_path = Path(project.file_path)

    if not original_path.exists():
        raise FileNotFoundError(f"Source file not found: {original_path}")

    output_filename = f"translated_{project.file_name}"
    output_path = original_path.parent / output_filename

    shutil.copyfile(original_path, output_path)

    return output_path


# ============================================================
# CERTIFICATION INJECTION
# ============================================================

def _inject_certification(project: TranslationProject, output_path: Path) -> None:

    temp_dir = Path(tempfile.mkdtemp())

    try:
        certification_pdf = temp_dir / "certification.pdf"
        merged_pdf = temp_dir / "merged_output.pdf"

        # ----------------------------------------------------
        # Validate language fields before generating cert
        # ----------------------------------------------------
        if not project.source_language or not project.target_language:
            raise ValueError("Source/Target language required for certification")

        # ----------------------------------------------------
        # Generate certification PDF
        # ----------------------------------------------------
        CertificationService.generate_certification_pdf(
            output_path=certification_pdf,
            user_name=project.user.full_name or "Certified Translator",
            source_language=project.source_language,
            target_language=project.target_language,
            override_text=project.certification_override_text,
        )

        # ----------------------------------------------------
        # Merge PDFs
        # ----------------------------------------------------
        PdfMergeService.append_pdf(
            original_pdf=output_path,
            append_pdf=certification_pdf,
            output_pdf=merged_pdf,
        )

        # ----------------------------------------------------
        # Atomic replace
        # ----------------------------------------------------
        shutil.move(str(merged_pdf), str(output_path))

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)