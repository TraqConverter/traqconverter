import uuid
from datetime import datetime

from sqlalchemy import Column, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class TranslationMemory(Base):
    __tablename__ = "translation_memory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)