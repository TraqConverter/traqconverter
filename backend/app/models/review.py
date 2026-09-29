from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class ReviewState(Base):
    """Per-project review data: the source-to-translation map, cached checks and dismissed check items."""

    __tablename__ = "review_states"

    project_id = Column(
        UUID(as_uuid=True), ForeignKey("translation_projects.id", ondelete="CASCADE"), primary_key=True
    )
    source_key = Column(String, nullable=True)
    source_map = Column(JSON, nullable=True)
    map_revision = Column(Integer, nullable=False, default=0, server_default="0")
    names = Column(JSON, nullable=True)
    untranslated = Column(JSON, nullable=True)
    checks = Column(JSON, nullable=True)
    dismissed = Column(JSON, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
