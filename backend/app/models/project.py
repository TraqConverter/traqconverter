import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class TranslationProject(Base):
    __tablename__ = "translation_projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)

    page_count = Column(Integer, nullable=False)
    credits_used = Column(Integer, nullable=False)

    status = Column(
        String,
        nullable=False,
        default="DRAFT"  # DRAFT / IN_PROGRESS / QUOTE_REQUESTED / COMPLETED
    )

    is_quote_request = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")