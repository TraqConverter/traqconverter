import uuid
from sqlalchemy import Column, String, Boolean, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    # === BILLING FIELDS ===
    subscription_status = Column(String, default="inactive")
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    monthly_credits = Column(Integer, default=0)
    extra_credits = Column(Integer, default=0)
    subscription_current_period_end = Column(DateTime, nullable=True)
    subscription_plan = Column(String, nullable=False, default="BASIC")

    # === ROLE FIELD ===
    role = Column(String, nullable=False, default="USER")