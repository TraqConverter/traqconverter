"""Pydantic schemas for team / membership / invite responses."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class TeamMemberOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: Optional[str] = None
    role: str
    is_owner: bool

    class Config:
        from_attributes = True


class TeamInviteOut(BaseModel):
    id: UUID
    email: EmailStr
    role: str
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TeamSnapshot(BaseModel):
    team_id: UUID
    team_name: str
    members: List[TeamMemberOut]
    pending_invites: List[TeamInviteOut]
