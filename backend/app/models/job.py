import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    source_language = Column(String, nullable=False)
    target_language = Column(String, nullable=False)

    page_count = Column(Integer, nullable=False)
    credits_used = Column(Integer, nullable=False)

    status = Column(String, default="TRANSLATING")

    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    team = relationship("Team")
