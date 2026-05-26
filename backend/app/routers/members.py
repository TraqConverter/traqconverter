from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.team import Team
from app.models.team_member import TeamMember, TeamInvite


router = APIRouter(prefix="/members", tags=["Members"])


# ============================================================
# Helpers
# ============================================================

def _get_team_for_user(db: Session, user: User) -> Team:
    """Resolve the team the user owns. Right now every user owns one team."""
    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if team:
        return team

    # Fallback — user is a *member* of someone else's team.
    membership = (
        db.query(TeamMember).filter(TeamMember.user_id == user.id).first()
    )
    if membership:
        team = db.query(Team).filter(Team.id == membership.team_id).first()
        if team:
            return team

    raise HTTPException(status_code=404, detail="No team found for this user")


def _is_owner(team: Team, user: User) -> bool:
    return team.owner_id == user.id


def _serialize_member(team: Team, user: User, role: str) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": role,
        "is_owner": team.owner_id == user.id,
    }


def _serialize_invite(invite: TeamInvite) -> dict:
    return {
        "id": str(invite.id),
        "email": invite.email,
        "role": invite.role,
        "status": invite.status,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
    }


# ============================================================
# Schemas
# ============================================================

class InvitePayload(BaseModel):
    email: EmailStr
    role: str = "MEMBER"


class RoleUpdate(BaseModel):
    role: str


# ============================================================
# LIST MEMBERS + PENDING INVITES
# ============================================================

@router.get("")
def list_members(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _get_team_for_user(db, current_user)

    # Owner first
    members = []
    owner = db.query(User).filter(User.id == team.owner_id).first()
    if owner:
        members.append(_serialize_member(team, owner, "OWNER"))

    rows = (
        db.query(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .filter(TeamMember.team_id == team.id)
        .order_by(TeamMember.created_at.asc())
        .all()
    )
    for tm, user in rows:
        # Skip the owner if they were added as a member entry too
        if user.id == team.owner_id:
            continue
        members.append(_serialize_member(team, user, tm.role))

    invites = (
        db.query(TeamInvite)
        .filter(TeamInvite.team_id == team.id, TeamInvite.status == "PENDING")
        .order_by(TeamInvite.created_at.desc())
        .all()
    )

    return {
        "team_id": str(team.id),
        "team_name": team.name,
        "members": members,
        "pending_invites": [_serialize_invite(i) for i in invites],
    }


# ============================================================
# INVITE BY EMAIL
# Behaviour:
#  - If an active user with this email already exists → add them directly
#    as a TeamMember and return { added: true }.
#  - Otherwise → create a PENDING TeamInvite that gets auto-accepted on
#    register/login of that email (handled in auth.py).
# ============================================================

@router.post("/invite")
def invite_member(
    payload: InvitePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _get_team_for_user(db, current_user)
    if not _is_owner(team, current_user):
        raise HTTPException(status_code=403, detail="Only the team owner can invite members")

    email = payload.email.strip().lower()
    role = payload.role.strip().upper() or "MEMBER"
    if role not in ("MEMBER", "ADMIN", "REVIEWER", "PM"):
        raise HTTPException(status_code=400, detail="Invalid role")

    # Owner can't invite themselves
    if current_user.email and current_user.email.lower() == email:
        raise HTTPException(status_code=400, detail="You're already on this team")

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        # Already a member?
        already = (
            db.query(TeamMember)
            .filter(
                TeamMember.team_id == team.id,
                TeamMember.user_id == existing_user.id,
            )
            .first()
        )
        if already:
            raise HTTPException(status_code=400, detail="That user is already on this team")

        membership = TeamMember(
            team_id=team.id,
            user_id=existing_user.id,
            role=role,
        )
        db.add(membership)
        db.commit()

        return {
            "added": True,
            "member": _serialize_member(team, existing_user, role),
        }

    # No user yet — create pending invite (or reuse one)
    pending = (
        db.query(TeamInvite)
        .filter(
            TeamInvite.team_id == team.id,
            TeamInvite.email == email,
            TeamInvite.status == "PENDING",
        )
        .first()
    )
    if pending:
        # Just bump the role if changed
        pending.role = role
        db.commit()
        db.refresh(pending)
        return {"invited": True, "invite": _serialize_invite(pending)}

    invite = TeamInvite(
        team_id=team.id,
        email=email,
        role=role,
        status="PENDING",
        invited_by=current_user.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    # Fire the invitation email via Resend. Failures don't break the
    # invite flow (the row is already in the DB and will auto-accept
    # on register/login), they just surface in the response so the
    # owner can retry from the UI.
    email_delivered = _send_invite_email(team, current_user, email, role)

    return {
        "invited": True,
        "invite": _serialize_invite(invite),
        "email_delivered": email_delivered,
    }


def _send_invite_email(
    team: Team,
    inviter: User,
    invitee_email: str,
    role: str,
) -> bool:
    """Send the invite email through Resend. Returns True on success,
    False if Resend isn't configured or the send failed (we always
    persist the invite either way so the auto-accept path still
    works)."""
    from urllib.parse import urlencode
    from app.config import settings as _settings
    from app.services.email_service import (
        send_email,
        render_invite_email,
        is_configured,
    )

    if not is_configured():
        # Local dev or unconfigured production — be loud about it.
        import logging
        logging.getLogger(__name__).info(
            "Invite stored but no email sent (RESEND_API_KEY missing). "
            "Recipient will be auto-added when they register/sign in "
            "with %s.",
            invitee_email,
        )
        return False

    base = (_settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
    register_url = (
        f"{base}/register?"
        + urlencode({"email": invitee_email, "team": team.name or ""})
    )

    subject, html = render_invite_email(
        inviter_name=(inviter.full_name or "").strip(),
        inviter_email=inviter.email,
        team_name=team.name or "your team",
        role=role,
        register_url=register_url,
    )
    return send_email(to=invitee_email, subject=subject, html=html)


# ============================================================
# CANCEL PENDING INVITE
# ============================================================

@router.delete("/invites/{invite_id}")
def cancel_invite(
    invite_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _get_team_for_user(db, current_user)
    if not _is_owner(team, current_user):
        raise HTTPException(status_code=403, detail="Only the team owner can cancel invites")

    invite = (
        db.query(TeamInvite)
        .filter(TeamInvite.id == invite_id, TeamInvite.team_id == team.id)
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    db.delete(invite)
    db.commit()
    return {"status": "cancelled"}


# ============================================================
# CHANGE ROLE
# ============================================================

@router.patch("/{user_id}")
def update_role(
    user_id: str,
    data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _get_team_for_user(db, current_user)
    if not _is_owner(team, current_user):
        raise HTTPException(status_code=403, detail="Only the team owner can change roles")

    if str(team.owner_id) == str(user_id):
        raise HTTPException(status_code=400, detail="The owner role can't be changed here")

    role = data.role.strip().upper()
    if role not in ("MEMBER", "ADMIN", "REVIEWER", "PM"):
        raise HTTPException(status_code=400, detail="Invalid role")

    membership = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team.id, TeamMember.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="That user isn't on this team")

    membership.role = role
    db.commit()

    user = db.query(User).filter(User.id == user_id).first()
    return {"member": _serialize_member(team, user, role)} if user else {"status": "ok"}


# ============================================================
# REMOVE MEMBER
# ============================================================

@router.delete("/{user_id}")
def remove_member(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _get_team_for_user(db, current_user)
    if not _is_owner(team, current_user):
        raise HTTPException(status_code=403, detail="Only the team owner can remove members")

    if str(team.owner_id) == str(user_id):
        raise HTTPException(status_code=400, detail="The owner can't be removed from their own team")

    membership = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team.id, TeamMember.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="That user isn't on this team")

    db.delete(membership)
    db.commit()
    return {"status": "removed"}


# ============================================================
# Internal helper used by auth.py during register/login —
# auto-accepts any pending invites for the user's email.
# ============================================================

def auto_accept_invites(db: Session, user: User) -> int:
    if not user.email:
        return 0
    invites = (
        db.query(TeamInvite)
        .filter(
            TeamInvite.email == user.email.lower(),
            TeamInvite.status == "PENDING",
        )
        .all()
    )
    accepted = 0
    for invite in invites:
        already = (
            db.query(TeamMember)
            .filter(
                TeamMember.team_id == invite.team_id,
                TeamMember.user_id == user.id,
            )
            .first()
        )
        if not already:
            db.add(
                TeamMember(
                    team_id=invite.team_id,
                    user_id=user.id,
                    role=invite.role,
                )
            )
        invite.status = "ACCEPTED"
        accepted += 1
    if accepted:
        db.commit()
    return accepted
