import json
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # project_id -> set of websockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, project_id: str):
        await websocket.accept()
        if project_id not in self.active_connections:
            self.active_connections[project_id] = set()
        self.active_connections[project_id].add(websocket)

    def disconnect(self, websocket: WebSocket, project_id: str):
        if project_id in self.active_connections:
            self.active_connections[project_id].discard(websocket)

    async def send_to_project(self, project_id: str, message: dict):
        """向项目的所有连接发送消息"""
        if project_id not in self.active_connections:
            return
        disconnected = set()
        for ws in self.active_connections[project_id]:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)
        # 清理断开的连接
        for ws in disconnected:
            self.active_connections[project_id].discard(ws)


# 全局连接管理器
ws_manager = ConnectionManager()
