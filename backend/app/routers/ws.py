from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List

router = APIRouter()

# 🔥 Connected clients per project
connections: Dict[str, List[WebSocket]] = {}


@router.websocket("/ws/projects/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    await websocket.accept()

    if project_id not in connections:
        connections[project_id] = []

    connections[project_id].append(websocket)

    try:
        while True:
            await websocket.receive_text()  # keep alive

    except WebSocketDisconnect:
        connections[project_id].remove(websocket)


# 🔥 BROADCAST FUNCTION
async def broadcast_progress(project_id: str, data: dict):
    if project_id not in connections:
        return

    dead_connections = []

    for ws in connections[project_id]:
        try:
            await ws.send_json(data)
        except:
            dead_connections.append(ws)

    for ws in dead_connections:
        connections[project_id].remove(ws)