import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class DocumentTemplate(Base):
    """A team's finished translation of one kind of document, reused for the next document of that kind."""

    __tablename__ = "document_templates"
    __table_args__ = (UniqueConstraint("team_id", "doc_key", "target_language", name="uq_template_team_key_lang"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_key = Column(String, nullable=False, index=True)
    target_language = Column(String, nullable=False)
    title = Column(String, nullable=False)
    doc_profile = Column(JSON, nullable=True)
    source_project_id = Column(
        UUID(as_uuid=True), ForeignKey("translation_projects.id", ondelete="SET NULL"), nullable=True
    )
    source_version = Column(Integer, nullable=True)
    s3_key = Column(String, nullable=False)
    source_text = Column(Text, nullable=False, default="")
    use_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PendingLearning(Base):
    """A paragraph the translator changed, waiting to be mined for terminology decisions."""

    __tablename__ = "pending_learning"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("translation_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    block_id = Column(String, nullable=True)
    before_text = Column(Text, nullable=False, default="")
    after_text = Column(Text, nullable=False, default="")
    origin = Column(String, nullable=False, default="typed")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    claimed_at = Column(DateTime, nullable=True)
