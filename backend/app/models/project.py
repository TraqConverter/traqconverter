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

    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    output_file = Column(String, nullable=True)

    page_count = Column(Integer, nullable=False)
    credits_used = Column(Integer, nullable=False)

    # ✅ Idempotency Key (NEW)
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

    # -----------------------------
    # Certification Injection Fields
    # -----------------------------
    add_certification = Column(Boolean, default=False, nullable=False)

    source_language = Column(String, nullable=True)
    target_language = Column(String, nullable=True)

    certification_override_text = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    retry_count = Column(Integer, nullable=False, default=0)
    last_heartbeat = Column(DateTime, nullable=True)

    # Relationship
    user = relationship("User", back_populates="projects")

    progress_percent = Column(Integer, nullable=False, default=0)