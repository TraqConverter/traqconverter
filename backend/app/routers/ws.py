from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List

router = APIRouter()

# 🔥 Connections grouped by:
# - "all" → all jobs dashboard listeners
# - project_id → specific project listeners
connections: Dict[str, List[WebSocket]] = {
    "all": []
}


# =========================================
# GLOBAL (Jobs Page)
# =========================================
@router.websocket("/ws/projects")
async def websocket_all(websocket: WebSocket):
    await websocket.accept()
    connections["all"].append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connections["all"]:
            connections["all"].remove(websocket)


# =========================================
# PROJECT-SPECIFIC
# =========================================
@router.websocket("/ws/projects/{project_id}")
async def websocket_project(websocket: WebSocket, project_id: str):
    await websocket.accept()

    if project_id not in connections:
        connections[project_id] = []

    connections[project_id].append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if project_id in connections and websocket in connections[project_id]:
            connections[project_id].remove(websocket)

            # 🔥 cleanup empty lists
            if not connections[project_id]:
                del connections[project_id]


# =========================================
# 🔥 BROADCAST FUNCTION (FIXED)
# =========================================
async def broadcast_progress(project_id: str, data: dict):
    payload = {
        "project_id": project_id,
        **data
    }

    # 🔥 send to BOTH:
    # - project-specific listeners
    # - global listeners (jobs page)
    targets = []

    if project_id in connections:
        targets.extend(connections[project_id])

    targets.extend(connections["all"])

    dead_connections = []

    for ws in targets:
        try:
            await ws.send_json(payload)
        except:
            dead_connections.append(ws)

    # 🔥 cleanup dead connections safely
    for ws in dead_connections:
        for key in list(connections.keys()):
            if ws in connections.get(key, []):
                connections[key].remove(ws)

                if key != "all" and not connections[key]:
                    del connections[key]