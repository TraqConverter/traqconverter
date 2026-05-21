import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    # === BILLING FIELDS (Stripe Metadata Only) ===
    subscription_status = Column(String, default="inactive")
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    subscription_current_period_end = Column(DateTime, nullable=True)
    subscription_plan = Column(String, nullable=False, default="BASIC")

    # === ROLE FIELD ===
    role = Column(String, nullable=False, default="USER")

    certification_file = Column(String, nullable=True)

    # Optional per-user company logo displayed at the top of the
    # certification page on every exported translation. Stored as an
    # S3 key (we already use S3 for project files), so the same
    # presigned-URL flow that fetches input files works here.
    logo_s3_key = Column(String, nullable=True)

    # Audit CRIT-8: bumped on password change to invalidate every JWT
    # issued before the change (existing sessions get logged out).
    token_version = Column(Integer, nullable=False, default=0)

    # ✅ Bidirectional relationship
    # Disambiguate which FK on TranslationProject this belongs to —
    # the table now has both `user_id` (creator) and `assignee_id`.
    projects = relationship(
        "TranslationProject",
        back_populates="user",
        foreign_keys="TranslationProject.user_id",
    )

    # Projects this user is currently assigned to work on.
    assigned_projects = relationship(
        "TranslationProject",
        foreign_keys="TranslationProject.assignee_id",
        viewonly=True,
    )