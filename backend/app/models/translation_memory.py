import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class TranslationMemory(Base):
    """One source sentence and its translation for a team and language pair (BCP-47, never 'auto')."""

    __tablename__ = "translation_memory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("translation_projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    source_language = Column(String, nullable=False)
    target_language = Column(String, nullable=False)

    source_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)
    # sha256 of the whitespace-normalised source text.
    source_hash = Column(String(64), nullable=False)
    # machine | approved | manual | import
    origin = Column(String, nullable=False, default="machine", server_default="machine")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


Index(
    "uq_tm_key",
    TranslationMemory.team_id,
    TranslationMemory.source_language,
    TranslationMemory.target_language,
    TranslationMemory.source_hash,
    unique=True,
)
