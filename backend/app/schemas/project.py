from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class ProjectStatusResponse(BaseModel):
    id: UUID
    status: str
    progress_percent: int
    retry_count: int
    created_at: datetime

    class Config:
        from_attributes = True