import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class TranslationSegment(Base):

    __tablename__ = "translation_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("translation_projects.id"),
        nullable=False
    )

    segment_index = Column(Integer, nullable=False)

    source_text = Column(Text, nullable=False)

    translated_text = Column(Text, nullable=True)

    # Reviewer-toggled green tick in the editor.
    approved = Column(Boolean, nullable=False, default=False)

    # Translation Memory match percentage at the time of translation
    # (0–100). Null when the segment was machine-translated without a TM hit.
    tm_pct = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("TranslationProject")
