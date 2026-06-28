import logging
from datetime import datetime
from typing import Any

from litestar import WebSocket
from sqlalchemy import select

from models.orm import ChatMessage

logger = logging.getLogger("chat_service")


class ChatService:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, db_factory) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New chat connection. Total users: {len(self.active_connections)}")

        with db_factory() as session:
            rows = session.execute(
                select(ChatMessage)
                .order_by(ChatMessage.timestamp.desc())
                .limit(50)
            ).scalars().all()

        if rows:
            history = [
                {
                    "type": "message",
                    "username": m.username,
                    "text": m.text,
                    "timestamp": int(m.timestamp.timestamp() * 1000),
                }
                for m in reversed(rows)
            ]
            await websocket.send_json({"type": "history", "messages": history})

    async def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Chat connection removed. Total users: {len(self.active_connections)}")

    async def broadcast_message(self, message: dict[str, Any], db_factory=None) -> None:
        message["timestamp"] = int(datetime.now().timestamp() * 1000)

        if message["type"] == "message" and db_factory:
            with db_factory() as session:
                session.add(ChatMessage(
                    username=message["username"],
                    text=message["text"],
                    message_type="message",
                ))
                session.commit()

        connections_to_remove = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to a client: {e}")
                connections_to_remove.append(connection)

        for connection in connections_to_remove:
            await self.disconnect(connection)
