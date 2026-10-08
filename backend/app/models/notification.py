import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

KINDS = (
    "assigned",
    "translation_done",
    "translation_failed",
    "client_paid",
    "client_claimed_paid",
    "client_downloaded",
    "files_expiring",
)


class Notification(Base):
    """An in-app notice for one user. Holds file names, amounts and statuses only, never a client's details."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(UUID(as_uuid=True), nullable=True)
    kind = Column(String(32), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(String(500), nullable=False, default="")
    link = Column(String(500), nullable=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("translation_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)
