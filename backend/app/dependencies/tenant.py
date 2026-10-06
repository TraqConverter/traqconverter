"""Tenant resolution helpers used by every router that needs to confirm
a project / segment / asset belongs to the caller's team.

Why this file exists
--------------------
Several routers (segments, export, project, certifications, etc.)
historically scoped queries by `current_user.id` which lets ANY logged-in
user read or rewrite a different tenant's projects via UUID guessing
(IDOR). All write paths should call `assert_project_access(db, project,
current_user)` before touching the row.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.roles import TEAM_MANAGER_ROLES, is_staff
from app.models.user import User
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.project import TranslationProject


def team_ids_for(db: Session, user: User) -> set:
    """Every team this user owns or is a member of."""
    ids = set()
    owned = db.query(Team.id).filter(Team.owner_id == user.id).all()
    for (tid,) in owned:
        ids.add(tid)
    memberships = (
        db.query(TeamMember.team_id).filter(TeamMember.user_id == user.id).all()
    )
    for (tid,) in memberships:
        ids.add(tid)
    return ids


def can_manage_team(db: Session, team: Team, user: User) -> bool:
    """Billing, payments and the stamp: the team owner or a team ADMIN."""
    if team is None:
        return False
    if team.owner_id == user.id:
        return True
    member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team.id, TeamMember.user_id == user.id)
        .first()
    )
    return bool(member and (member.role or "").upper() in TEAM_MANAGER_ROLES)


def get_user_project_or_404(
    db: Session, project_id, user: User
) -> TranslationProject:
    """Fetch a project the user is allowed to see (owner or team member),
    or raise 404. Always use this instead of querying by user_id directly.

    Note: 404 not 403 — we don't reveal whether a project ID exists in
    another tenant.
    """
    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    allowed = team_ids_for(db, user)
    if project.team_id not in allowed:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def assert_project_access(
    db: Session, project: TranslationProject, user: User
) -> None:
    """Raise 404 if `project` doesn't belong to one of the user's teams."""
    allowed = team_ids_for(db, user)
    if project.team_id not in allowed:
        raise HTTPException(status_code=404, detail="Project not found")


def can_manage_project(db: Session, project: TranslationProject, user: User) -> bool:
    """Destructive actions: the uploader, the team owner, or a team ADMIN/PM."""
    if project.user_id == user.id or is_staff(user):
        return True
    team = db.query(Team).filter(Team.id == project.team_id).first()
    if team and team.owner_id == user.id:
        return True
    member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == project.team_id, TeamMember.user_id == user.id)
        .first()
    )
    return bool(member and (member.role or "").upper() in ("ADMIN", "PM"))
