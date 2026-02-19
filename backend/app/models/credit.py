import uuid
from datetime import datetime

from sqlalchemy import Column, Integer, ForeignKey, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base

class CreditWallet(Base):
    __tablename__ = "credit_wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)

    balance = Column(Integer, default=0)
    monthly_allowance = Column(Integer, default=0)
    resets_at = Column(DateTime, nullable=True)

    team = relationship("Team")

class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("credit_wallets.id"), nullable=False)

    type = Column(String, nullable=False)  # SUBSCRIPTION_GRANT, PURCHASE, USAGE
    amount = Column(Integer, nullable=False)
    job_id = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    wallet = relationship("CreditWallet")
