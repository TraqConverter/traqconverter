import uuid
from sqlalchemy import Column, String, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Glossary(Base):
    __tablename__ = "glossary"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Audit HIGH-2: this column was literally named `user_id` while
    # FK'ing to `teams.id`. Renamed to match what it actually points at.
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
