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

    # --------------------------------
    # Ownership
    # --------------------------------
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    # Optional: which team member is currently working on this project.
    assignee_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --------------------------------
    # File Info
    # --------------------------------
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    output_file = Column(String, nullable=True)

    # --------------------------------
    # Billing
    # --------------------------------
    page_count = Column(Integer, nullable=False)
    credits_used = Column(Integer, nullable=False)

    # --------------------------------
    # Idempotency Protection
    # --------------------------------
    idempotency_key = Column(
        String,
        nullable=True,
        unique=True,
        index=True
    )

    # --------------------------------
    # Processing Status
    # --------------------------------
    status = Column(
        Enum(ProjectStatus, name="project_status_enum"),
        nullable=False,
        default=ProjectStatus.PENDING
    )

    # 🔥 EXISTING
    progress_percent = Column(Integer, nullable=False, default=0)

    # 🔥 NEW (REAL PROGRESS TRACKING)
    total_segments = Column(Integer, nullable=False, default=0)
    translated_segments = Column(Integer, nullable=False, default=0)

    retry_count = Column(Integer, nullable=False, default=0)
    last_heartbeat = Column(DateTime, nullable=True)

    # --------------------------------
    # Per-project translation options (toggled on the new-project page)
    # --------------------------------
    add_certification = Column(Boolean, default=False, nullable=False)
    use_tm = Column(Boolean, default=True, nullable=False)
    apply_glossary = Column(Boolean, default=True, nullable=False)

    # --------------------------------
    # Language Pair
    # --------------------------------
    source_language = Column(String, nullable=False, default="English")
    target_language = Column(String, nullable=False, default="Spanish")

    # --------------------------------
    # AI Model Selection
    # --------------------------------
    model = Column(String, nullable=False, default="balanced")

    # --------------------------------
    # Review pipeline status (post-translation)
    # DRAFT → IN_REVIEW → CERTIFIED
    # --------------------------------
    review_status = Column(String, nullable=False, default="DRAFT")

    # Detected on upload — drives which rebuild path runs at export time.
    # PDF / DOCX / IMAGE / TXT
    source_kind = Column(String, nullable=True)

    # --------------------------------
    # Certification
    # --------------------------------
    certification_override_text = Column(String, nullable=True)
    # Optional team-scoped cert template (from the Certifications
    # library). When set, the export pipeline downloads this DOCX,
    # substitutes {{tokens}} with project/user values, and uses the
    # result as the certification page instead of the hardcoded
    # "I hereby certify..." block.
    certification_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("certifications.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --------------------------------
    # Metadata
    # --------------------------------
    created_at = Column(DateTime, default=datetime.utcnow)

    # --------------------------------
    # Relationships
    # --------------------------------
    user = relationship("User", foreign_keys=[user_id], back_populates="projects")
    team = relationship("Team")
    assignee = relationship("User", foreign_keys=[assignee_id])
