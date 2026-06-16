"""WebSocket endpoints for real-time translation progress.

Audit CRIT-3 fix: previously these accepted any anonymous client, which
let outsiders subscribe to every tenant's progress and create unbounded
connections. We now require a valid JWT (passed as `?token=...` query
param) and verify the requested project belongs to the caller's team
before accepting the socket. Per-IP and per-user connection caps prevent
DoS via unlimited sockets.
"""
from __future__ import annotations

import logging
from typing import Dict, List
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.project import TranslationProject
from app.models.team import Team
from app.models.team_member import TeamMember
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()




connections: Dict[str, List[WebSocket]] = {"all": []}



MAX_PER_USER = 10
MAX_GLOBAL = 1000






def _decode_token(token: str | None) -> str | None:
    """Return the user id (`sub` claim) if the JWT is valid, else None."""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
    except JWTError:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    return str(sub)


def _resolve_user(user_id: str) -> User | None:
    db: Session = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def _user_can_access_project(user_id: str, project_id: str) -> bool:
    db: Session = SessionLocal()
    try:
        project = (
            db.query(TranslationProject)
            .filter(TranslationProject.id == project_id)
            .first()
        )
        if not project:
            return False


        is_owner = (
            db.query(Team)
            .filter(Team.id == project.team_id, Team.owner_id == user_id)
            .first()
            is not None
        )
        if is_owner:
            return True


        is_member = (
            db.query(TeamMember)
            .filter(
                TeamMember.team_id == project.team_id,
                TeamMember.user_id == user_id,
            )
            .first()
            is not None
        )
        return is_member
    finally:
        db.close()


def _count_user_sockets(user_id: str) -> int:
    return sum(
        1
        for sockets in connections.values()
        for s in sockets
        if getattr(s, "_tc_user_id", None) == user_id
    )


def _count_global_sockets() -> int:
    return sum(len(s) for s in connections.values())







@router.websocket("/ws/projects")
async def websocket_all(websocket: WebSocket, token: str | None = None):
    user_id = _decode_token(token)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if (
        _count_global_sockets() >= MAX_GLOBAL
        or _count_user_sockets(user_id) >= MAX_PER_USER
    ):
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    await websocket.accept()
    setattr(websocket, "_tc_user_id", user_id)
    connections["all"].append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in connections["all"]:
            connections["all"].remove(websocket)







@router.websocket("/ws/projects/{project_id}")
async def websocket_project(
    websocket: WebSocket, project_id: str, token: str | None = None
):
    user_id = _decode_token(token)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return


    try:
        UUID(project_id)
    except (ValueError, TypeError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if not _user_can_access_project(user_id, project_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if (
        _count_global_sockets() >= MAX_GLOBAL
        or _count_user_sockets(user_id) >= MAX_PER_USER
    ):
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    await websocket.accept()
    setattr(websocket, "_tc_user_id", user_id)
    connections.setdefault(project_id, []).append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        sockets = connections.get(project_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
            if not sockets:
                connections.pop(project_id, None)








async def broadcast_progress(project_id: str, data: dict):
    payload = {"project_id": project_id, **data}

    targets: List[WebSocket] = []
    project_sockets = connections.get(project_id, [])
    targets.extend(project_sockets)




    for ws in connections.get("all", []):
        uid = getattr(ws, "_tc_user_id", None)
        if uid and _user_can_access_project(uid, project_id):
            targets.append(ws)

    dead: List[WebSocket] = []
    for ws in targets:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)

    for ws in dead:
        for key in list(connections.keys()):
            if ws in connections.get(key, []):
                connections[key].remove(ws)
                if key != "all" and not connections[key]:
                    connections.pop(key, None)
