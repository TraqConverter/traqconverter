from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.database import Base


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    id = Column(String, primary_key=True, index=True)
    event_type = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
