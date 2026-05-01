import uuid
from sqlalchemy import Column, String, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Glossary(Base):
    __tablename__ = "glossary"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)

    source_language = Column(String, nullable=False)
    target_language = Column(String, nullable=False)

    source_term = Column(Text, nullable=False)
    target_term = Column(Text, nullable=False)

    # Free-form note about when/how to use the term.
    notes = Column(Text, nullable=True)

    # Auto-incremented every time the term is applied in a translation.
    usage_count = Column(Integer, nullable=False, default=0)
