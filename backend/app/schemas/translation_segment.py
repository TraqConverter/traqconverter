from pydantic import BaseModel
from uuid import UUID


class TranslationSegmentOut(BaseModel):
    id: UUID
    segment_index: int
    source_text: str
    translated_text: str

    class Config:
        from_attributes = True