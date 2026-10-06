from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.dependencies import get_current_user
from app.core.plan_features import PLANS, SALES_EMAIL, SEAT_LIMITS, next_plan_with_more_seats
from app.dependencies.feature_guard import _is_admin, effective_plan, require_feature
from app.models.user import User
from app.models.team import Team
from app.models.team_member import TeamMember, TeamInvite


router = APIRouter(prefix="/members", tags=["Members"])






def _get_team_for_user(db: Session, user: User) -> Team:
    """Resolve the team the user owns. Right now every user owns one team."""
    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if team:
        return team


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






def _seats_taken(db: Session, team: Team) -> int:
    """Owner, members and pending invites: an invite holds its seat until it's accepted or cancelled."""
    members = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team.id, TeamMember.user_id != team.owner_id)
        .count()
    )
    pending = (
        db.query(TeamInvite)
        .filter(TeamInvite.team_id == team.id, TeamInvite.status == "PENDING")
        .count()
    )
    return 1 + members + pending


def seat_limit_message(plan: str) -> str:
    limit = SEAT_LIMITS.get(plan, 1)
    name = next((p["name"] for p in PLANS if p["code"] == plan), plan.title())
    upgrade = next_plan_with_more_seats(plan)
    if upgrade:
        then = f"Upgrade to {upgrade['name']} for up to {upgrade['seats']}."
    else:
        then = f"Contact us at {SALES_EMAIL} for a larger team."
    return (
        f"Your {name} plan includes up to {limit} team members, you included, "
        f"and pending invites count too. {then}"
    )


def _check_seat_available(db: Session, team: Team, user: User) -> None:
    if _is_admin(user):
        return
    plan = effective_plan(db, user)
    if _seats_taken(db, team) >= SEAT_LIMITS.get(plan, 1):
        raise HTTPException(status_code=403, detail=seat_limit_message(plan))


class InvitePayload(BaseModel):
    email: EmailStr
    role: str = "MEMBER"


class RoleUpdate(BaseModel):
    role: str






@router.get("")
def list_members(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _get_team_for_user(db, current_user)


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
        "seats": {
            "used": _seats_taken(db, team),
            "limit": None if _is_admin(current_user) else SEAT_LIMITS.get(effective_plan(db, current_user), 1),
        },
    }











@router.post("/invite", dependencies=[Depends(require_feature("team_collaboration"))])
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


    if current_user.email and current_user.email.lower() == email:
        raise HTTPException(status_code=400, detail="You're already on this team")

    existing_user = db.query(User).filter(func.lower(User.email) == email).first()
    if existing_user:

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

        _check_seat_available(db, team, current_user)
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

        pending.role = role
        db.commit()
        db.refresh(pending)
        return {"invited": True, "invite": _serialize_invite(pending)}

    _check_seat_available(db, team, current_user)
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





    email_delivered = _send_invite_email(team, current_user, email, role, invite.token)

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
    invite_token: str,
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
        + urlencode({"email": invitee_email, "team": team.name or "", "invite": invite_token})
    )

    subject, html = render_invite_email(
        inviter_name=(inviter.full_name or "").strip(),
        inviter_email=inviter.email,
        team_name=team.name or "your team",
        role=role,
        register_url=register_url,
    )
    return send_email(to=invitee_email, subject=subject, html=html)






@router.delete("/invites/{invite_id}")
def cancel_invite(
    invite_id: UUID,
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






@router.patch("/{user_id}")
def update_role(
    user_id: UUID,
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






@router.delete("/{user_id}")
def remove_member(
    user_id: UUID,
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







def auto_accept_invites(db: Session, user: User, token: str | None) -> int:
    """Accept the pending invite carrying `token` if it was sent to this user's email."""
    if not user.email or not token:
        return 0
    invites = (
        db.query(TeamInvite)
        .filter(
            TeamInvite.email == user.email.lower(),
            TeamInvite.status == "PENDING",
            TeamInvite.token == token,
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


class _AcceptInvitePayload(BaseModel):
    token: str


@router.post("/invites/accept")
def accept_invite(
    payload: _AcceptInvitePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Signed-in users join via the invite link's token; the invite must be addressed to their email."""
    if not auto_accept_invites(db, current_user, payload.token):
        raise HTTPException(status_code=404, detail="Invite not found or not addressed to this account")
    return {"accepted": True}
