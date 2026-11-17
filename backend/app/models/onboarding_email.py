from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class OnboardingEmail(Base):
    """One row per trial sign-up; a user without a row gets no onboarding email."""

    __tablename__ = "onboarding_emails"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    signed_up_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    welcome_sent_at = Column(DateTime, nullable=True)
    nudge_sent_at = Column(DateTime, nullable=True)
    last_chance_sent_at = Column(DateTime, nullable=True)
    trial_ended_sent_at = Column(DateTime, nullable=True)
    unsubscribed_at = Column(DateTime, nullable=True)
