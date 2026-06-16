import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class ProjectStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


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





    review_status = Column(String, nullable=False, default="DRAFT")



    source_kind = Column(String, nullable=True)




    certification_override_text = Column(String, nullable=True)





    certification_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("certifications.id", ondelete="SET NULL"),
        nullable=True,
    )








    authored_docx_s3_key = Column(String, nullable=True)




    edited_html = Column(String, nullable=True)




    created_at = Column(DateTime, default=datetime.utcnow)




    user = relationship("User", foreign_keys=[user_id], back_populates="projects")
    team = relationship("Team")
    assignee = relationship("User", foreign_keys=[assignee_id])
