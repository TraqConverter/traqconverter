import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, String, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Glossary(Base):
    __tablename__ = "glossary"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)



    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_language = Column(String, nullable=False)
    target_language = Column(String, nullable=False)

    source_term = Column(Text, nullable=False)
    target_term = Column(Text, nullable=False)

    notes = Column(Text, nullable=True)
    usage_count = Column(Integer, nullable=False, default=0)

    # 'manual' (typed by the team), 'learned' (mined from edits) or 'rejected' (kept so it isn't relearned).
    origin = Column(String, nullable=False, default="manual", server_default="manual")
    confidence = Column(Float, nullable=True)
    learned_from_project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("translation_projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)
