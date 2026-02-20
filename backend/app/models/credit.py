from sqlalchemy import Column, Integer, ForeignKey, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
import uuid


class CreditWallet(Base):
    __tablename__ = "credit_wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"))

    # 🔹 Split credit pools
    subscription_credits = Column(Integer, default=0)
    purchased_credits = Column(Integer, default=0)

    # 🔹 Plan configuration
    plan_type = Column(String, default="STARTER")
    monthly_allowance = Column(Integer, default=39)

    subscription_status = Column(String, default="INACTIVE")
    subscription_expires_at = Column(DateTime, nullable=True)

    transactions = relationship("CreditTransaction", back_populates="wallet")


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("credit_wallets.id"))

    type = Column(String, nullable=False)  # USAGE, PURCHASE, SUBSCRIPTION_GRANT
    amount = Column(Integer, nullable=False)

    wallet = relationship("CreditWallet", back_populates="transactions")