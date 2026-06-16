import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
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


    approved = Column(Boolean, nullable=False, default=False)



    tm_pct = Column(Integer, nullable=True)







    layout_meta = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("TranslationProject")
