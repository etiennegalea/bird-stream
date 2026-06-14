import logging
from datetime import datetime
from typing import Any

from litestar import WebSocket

logger = logging.getLogger("chat_service")


class ChatService:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.chat_history: list[dict[str, Any]] = []
        self.max_history = 500

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            f"New chat connection. Total chat users: {len(self.active_connections)}"
        )

        if self.chat_history:
            await websocket.send_json(
                {"type": "history", "messages": self.chat_history}
            )

    async def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                f"Chat connection removed. Total chat users: {len(self.active_connections)}"
            )

    async def broadcast_message(self, message: dict[str, Any]) -> None:
        message["timestamp"] = int(datetime.now().timestamp() * 1000)
        if message["type"] != "system":
            self.chat_history.append(message)

        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history :]

        connections_to_remove = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to a client: {e}")
                connections_to_remove.append(connection)

        for connection in connections_to_remove:
            await self.disconnect(connection)
