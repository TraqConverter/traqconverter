import uuid
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class CreditWallet(Base):
    __tablename__ = "credit_wallets"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        unique=True,
        nullable=False
    )

    subscription_credits = Column(Integer, default=0)
    purchase_credits = Column(Integer, default=0)

    subscription_expiry = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="wallet")

    @property
    def total_credits(self):
        return self.subscription_credits + self.purchase_credits