import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, String, Text, Integer, DateTime, ForeignKey, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Certification(Base):
    """A team-scoped library entry: a Word certification template or a
    supporting file attached to delivered translations. kind is derived from
    the file type (TEMPLATE for .docx, OTHER otherwise); old rows may hold
    the legacy user-chosen values.

    file_hash is a SHA-256 of the uploaded bytes — surfaced in the UI so the
    document can be independently verified ("tamper-evident hashes").
    """

    __tablename__ = "certifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)

    kind = Column(String, nullable=False, default="OTHER")
    notes = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # One per team (partial unique index); used when a project has no template of its own.
    is_default = Column(Boolean, nullable=False, default=False, server_default=false())

    uploader = relationship("User")
