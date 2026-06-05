"""Pydantic schemas for user-related API responses.

Routes were previously building these inline as plain dicts. Defining
them centrally lets FastAPI emit accurate OpenAPI specs and lets future
endpoints use `response_model=UserOut` for type safety.
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: Optional[str] = None
    role: str = "USER"
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None

    class Config:
        from_attributes = True


class UserPublic(BaseModel):
    """Trimmed-down user shape used in member lists / assignee fields."""

    id: UUID
    email: EmailStr
    full_name: Optional[str] = None

    class Config:
        from_attributes = True
