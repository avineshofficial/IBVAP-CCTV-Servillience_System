"""
IBVAP — WebSocket Alert Manager
==================================
Real-time alert streaming to connected dashboard clients.
"""

import json
import logging
from typing import Set
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class AlertWebSocketManager:
    """
    Manages WebSocket connections for real-time alert streaming.
    Clients connect to /ws/alerts and receive push notifications.
    """

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._message_count = 0

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self._connections.add(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self._connections)}")

        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": "IBVAP Alert Stream connected",
            "active_connections": len(self._connections),
        })

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected client."""
        self._connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self._connections)}")

    async def broadcast(self, message: dict):
        """Send a message to all connected clients."""
        if not self._connections:
            return

        self._message_count += 1
        message["message_id"] = self._message_count

        disconnected = set()
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)

        # Clean up disconnected clients
        for ws in disconnected:
            self._connections.discard(ws)

    async def send_to(self, websocket: WebSocket, message: dict):
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception:
            self._connections.discard(websocket)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Global singleton
alert_manager = AlertWebSocketManager()
