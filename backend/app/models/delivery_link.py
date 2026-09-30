import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class DeliveryLink(Base):
    """A link the translator sends a client: a snapshot of one export, downloadable without an account until it expires."""

    __tablename__ = "delivery_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("translation_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Only the sha256 of the token is kept; the prefix is there so the translator can tell links apart.
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    token_prefix = Column(String(12), nullable=False)
    kind = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    # Cleared once the snapshot is deleted from storage.
    file_key = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    download_count = Column(Integer, nullable=False, default=0)
    last_downloaded_at = Column(DateTime, nullable=True)
