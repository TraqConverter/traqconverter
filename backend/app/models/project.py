import uuid
from datetime import datetime
from sqlalchemy import JSON, Column, String, Integer, DateTime, Boolean, ForeignKey, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class ProjectStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


MODE_TRANSLATE = "translate"
MODE_DTP = "dtp"
PROJECT_MODES = (MODE_TRANSLATE, MODE_DTP)


def is_dtp(project) -> bool:
    return getattr(project, "mode", None) == MODE_DTP


class TranslationProject(Base):
    __tablename__ = "translation_projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)




    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)

    assignee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )




    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    output_file = Column(String, nullable=True)




    page_count = Column(Integer, nullable=False)
    credits_used = Column(Integer, nullable=False)




    idempotency_key = Column(
        String,
        nullable=True,
        unique=True,
        index=True
    )




    status = Column(
        Enum(ProjectStatus, name="project_status_enum"),
        nullable=False,
        default=ProjectStatus.PENDING
    )


    progress_percent = Column(Integer, nullable=False, default=0)
    # reading | translating | rebuilding | finishing while PROCESSING; see services/job_progress.py.
    progress_stage = Column(String(20), nullable=True)
    progress_detail = Column(String(120), nullable=True)
    stage_started_at = Column(DateTime, nullable=True)


    total_segments = Column(Integer, nullable=False, default=0)
    translated_segments = Column(Integer, nullable=False, default=0)

    retry_count = Column(Integer, nullable=False, default=0)
    last_heartbeat = Column(DateTime, nullable=True)




    add_certification = Column(Boolean, default=False, nullable=False)
    use_tm = Column(Boolean, default=True, nullable=False)
    apply_glossary = Column(Boolean, default=True, nullable=False)




    source_language = Column(String, nullable=False, default="English")
    target_language = Column(String, nullable=False, default="Spanish")




    model = Column(String, nullable=False, default="balanced")
    ai_instructions = Column(Text, nullable=True)
    # "translate", or "dtp": an editable same-language copy of the original.
    mode = Column(String, nullable=False, default=MODE_TRANSLATE, server_default=MODE_TRANSLATE)





    review_status = Column(String, nullable=False, default="DRAFT")



    source_kind = Column(String, nullable=True)




    certification_override_text = Column(String, nullable=True)





    certification_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("certifications.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The translator picked the built-in page, so the team default doesn't apply.
    certification_standard = Column(Boolean, default=False, server_default="false", nullable=False)








    authored_docx_s3_key = Column(String, nullable=True)




    edited_html = Column(String, nullable=True)

    revision_count = Column(Integer, nullable=False, default=0, server_default="0")
    ai_edits_used = Column(Integer, nullable=False, default=0, server_default="0")
    rebuild_status = Column(String, nullable=True)
    rebuild_error = Column(String, nullable=True)
    rebuild_started_at = Column(DateTime, nullable=True)
    failure_reason = Column(String, nullable=True)
    document_version = Column(Integer, nullable=False, default=0, server_default="0")
    doc_profile = Column(JSON, nullable=True)
    doc_key = Column(String, nullable=True, index=True)
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_templates.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    batch_id = Column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )




    created_at = Column(DateTime, default=datetime.utcnow)




    user = relationship("User", foreign_keys=[user_id], back_populates="projects")
    team = relationship("Team")
    assignee = relationship("User", foreign_keys=[assignee_id])


# Registers document_templates so the template_id foreign key resolves.
import app.models.learning  # noqa: E402,F401
import app.models.batch  # noqa: E402,F401
