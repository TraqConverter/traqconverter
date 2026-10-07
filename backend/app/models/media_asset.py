import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

NAME_MAX = 80
KINDS = ("stamp", "logo", "signature", "other")
# Kinds the app picks by the project's target language.
AUTO_KINDS = ("stamp", "logo")


class MediaAsset(Base):
    """A team's picture (stamp, logo, signature) that the editor and the certification page can use."""

    __tablename__ = "media_assets"
    # The unique index on auto_use per (team, kind, coalesce(language, '')) lives in the migration.

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(NAME_MAX), nullable=False)
    kind = Column(String(16), nullable=False, default="other")
    language = Column(String(8), nullable=True)
    s3_key = Column(String, nullable=False)
    mime_type = Column(String(40), nullable=True)
    width_px = Column(Integer, nullable=True)
    height_px = Column(Integer, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    auto_use = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())
