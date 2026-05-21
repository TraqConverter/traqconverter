import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


# ============================================================
# CREDIT WALLET
# ============================================================

class CreditWallet(Base):
    __tablename__ = "credit_wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"))

    # Dual bucket credit pools
    subscription_credits = Column(Integer, default=0)
    purchased_credits = Column(Integer, default=0)

    # Plan configuration
    plan_type = Column(String, default="STARTER")
    subscription_status = Column(String, default="INACTIVE")
    subscription_expires_at = Column(DateTime, nullable=True)

    # Bidirectional relationship
    transactions = relationship(
        "CreditTransaction",
        back_populates="wallet",
        cascade="all, delete-orphan"
    )


# ============================================================
# CREDIT TRANSACTION
# ============================================================

class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("credit_wallets.id"))

    type = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)

    # Project or Stripe reference
    reference_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Reverse relationship (REQUIRED)
    wallet = relationship(
        "CreditWallet",
        back_populates="transactions"
    )