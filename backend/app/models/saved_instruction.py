import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

NAME_MAX = 80


class SavedInstruction(Base):
    """A team's reusable instructions for the AI, e.g. one client's style."""

    __tablename__ = "saved_instructions"
    __table_args__ = (
        Index("uq_saved_instruction_team_name", "team_id", func.lower("name"), unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(NAME_MAX), nullable=False)
    text = Column(Text, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
