import logging
from datetime import datetime
from typing import Any

from litestar import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from models.orm import ChatMessage, User

logger = logging.getLogger("chat_service")


class ChatService:
    def __init__(self):
        self.active_connections: dict[WebSocket, str] = {}
        self.account_sockets: set[WebSocket] = set()
        self.user_id_map: dict[WebSocket, int | None] = {}

    def active_usernames(self) -> set[str]:
        return set(self.active_connections.values())

    def is_account_user(self, websocket: WebSocket) -> bool:
        return websocket in self.account_sockets

    def get_user_id(self, websocket: WebSocket) -> int | None:
        return self.user_id_map.get(websocket)

    async def connect(self, websocket: WebSocket, username: str, is_account: bool, user_id: int | None, db_factory) -> None:
        await websocket.accept()
        self.active_connections[websocket] = username
        self.user_id_map[websocket] = user_id
        if is_account:
            self.account_sockets.add(websocket)
        logger.info(f"New chat connection. Total users: {len(self.active_connections)}")

        with db_factory() as session:
            rows = session.execute(
                select(ChatMessage)
                .options(joinedload(ChatMessage.user))
                .order_by(ChatMessage.timestamp.desc())
                .limit(50)
            ).scalars().all()

        if rows:
            history = [
                {
                    "type": "message",
                    "sender_type": m.sender_type,
                    "username": (m.user.username if m.sender_type == "account" and m.user else m.username),
                    "user_id": m.user_id,
                    "avatar": (m.user.avatar if m.sender_type == "account" and m.user else None),
                    "is_account": m.sender_type == "account",
                    "text": m.text,
                    "timestamp": int(m.timestamp.timestamp() * 1000),
                }
                for m in reversed(rows)
            ]
            await websocket.send_json({"type": "history", "messages": history})

    async def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.pop(websocket, None)
        self.account_sockets.discard(websocket)
        self.user_id_map.pop(websocket, None)
        logger.info(f"Chat connection removed. Total users: {len(self.active_connections)}")

    async def broadcast_message(self, message: dict[str, Any], db_factory=None) -> None:
        message["timestamp"] = int(datetime.now().timestamp() * 1000)

        if message["type"] == "message" and db_factory:
            user_id = message.get("user_id")
            sender_type = message.get("sender_type", "guest")
            with db_factory() as session:
                if sender_type == "account" and user_id:
                    user = session.get(User, user_id)
                    if user:
                        message["username"] = user.username
                        message["avatar"] = user.avatar
                session.add(ChatMessage(
                    user_id=user_id,
                    username=message["username"],
                    sender_type=sender_type,
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
