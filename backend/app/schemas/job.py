from pydantic import BaseModel


class JobCreate(BaseModel):
    source_language: str
    target_language: str
    page_count: int


class JobResponse(BaseModel):
    id: str
    source_language: str
    target_language: str
    page_count: int
    credits_used: int
    status: str
