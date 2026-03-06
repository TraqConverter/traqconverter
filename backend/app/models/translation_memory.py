from sqlalchemy import Column, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import Index
import uuid

from app.database import Base


class TranslationMemory(Base):

    __tablename__ = "translation_memory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)

    source_language = Column(String, nullable=False)
    target_language = Column(String, nullable=False)

    source_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)

Index(
    "idx_tm_lookup",
    TranslationMemory.team_id,
    TranslationMemory.source_language,
    TranslationMemory.target_language,
    TranslationMemory.source_text
)