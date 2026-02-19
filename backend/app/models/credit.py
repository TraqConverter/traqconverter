from sqlalchemy import Column, Integer, ForeignKey, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import uuid


class CreditWallet(Base):
    __tablename__ = "credit_wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"))

    balance = Column(Integer, default=0)

    # Plan configuration
    plan_type = Column(String, default="STARTER")  # STARTER / PRO / ENTERPRISE
    monthly_allowance = Column(Integer, default=39)

    subscription_status = Column(String, default="INACTIVE")
    # INACTIVE / ACTIVE / CANCELED / EXPIRED

    subscription_expires_at = Column(DateTime, nullable=True)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("credit_wallets.id"))
    amount = Column(Integer)
    type = Column(String)  # SUBSCRIPTION_GRANT / PURCHASE / USAGE
    created_at = Column(DateTime)
