import uuid
from datetime import datetime

from sqlalchemy import Column, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class SegmentComment(Base):
    __tablename__ = "segment_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    segment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("translation_segments.id"),
        nullable=False
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True  # keep flexible for now
    )

    text = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    resolved = Column(Boolean, default=False)