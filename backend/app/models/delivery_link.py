import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, false
from sqlalchemy.dialects.postgresql import JSONB, UUID

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
    # The token encrypted with the app secret, so the team can copy the link again. Lookups still use token_hash.
    token_sealed = Column(String, nullable=True)
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

    # Protected links show a watermarked preview until the translator unlocks them after payment.
    protected = Column(Boolean, nullable=False, default=False, server_default=false())
    amount_cents = Column(Integer, nullable=True)
    currency = Column(String(3), nullable=False, default="EUR", server_default="EUR")
    paid_claimed_at = Column(DateTime, nullable=True)
    unlocked_at = Column(DateTime, nullable=True)
    unlocked_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Set when Stripe confirms a payment on the team's account; the link unlocks itself.
    stripe_payment_intent = Column(String(255), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    # Counted when the link is made; the original's pages are left out of the preview.
    preview_pages = Column(Integer, nullable=True)
    original_pages = Column(Integer, nullable=True)
    # Storage keys of the rendered preview PNGs, in page order; cleared when they're deleted.
    preview_keys = Column(JSONB, nullable=True)
