import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Batch(Base):
    """Documents from one client uploaded together, translated with the same names and terms."""

    __tablename__ = "batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Set once the first document's terms were extracted (even zero); later documents may then run in parallel.
    terms_ready_at = Column(DateTime, nullable=True)


class BatchTerm(Base):
    __tablename__ = "batch_terms"
    __table_args__ = (UniqueConstraint("batch_id", "target_language", "source_key", name="uq_batch_term"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    target_language = Column(String, nullable=False)
    source_term = Column(String, nullable=False)
    source_key = Column(String, nullable=False)
    target_term = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="term")
    first_project_id = Column(
        UUID(as_uuid=True), ForeignKey("translation_projects.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
