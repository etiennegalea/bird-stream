import logging
from datetime import datetime
from time import monotonic
from typing import Any

from litestar import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from models.orm import ChatMessage, User

logger = logging.getLogger("chat_service")

# Leaky-bucket parameters
_BUCKET_CAPACITY = 8    # maximum burst (tokens)
_BUCKET_DRAIN_RATE = 1.0  # tokens drained per second (sustainable send rate)


class LeakyBucket:
    """Leaky-bucket rate limiter. Each message costs 1 token."""

    def __init__(self, capacity: float = _BUCKET_CAPACITY, drain_rate: float = _BUCKET_DRAIN_RATE):
        self.capacity = capacity
        self.drain_rate = drain_rate
        self._level = 0.0
        self._last_check = monotonic()

    def consume(self) -> bool:
        """Return True if the message is allowed, False if the bucket is full."""
        now = monotonic()
        elapsed = now - self._last_check
        self._last_check = now
        self._level = max(0.0, self._level - elapsed * self.drain_rate)
        if self._level + 1.0 > self.capacity:
            return False
        self._level += 1.0
        return True


class ChatService:
    def __init__(self):
        self.active_connections: dict[WebSocket, str] = {}
        self.account_sockets: set[WebSocket] = set()
        self.user_id_map: dict[WebSocket, int | None] = {}
        self.rate_limiters: dict[WebSocket, LeakyBucket] = {}

    def active_usernames(self) -> set[str]:
        return set(self.active_connections.values())

    def is_account_user(self, websocket: WebSocket) -> bool:
        return websocket in self.account_sockets

    def get_user_id(self, websocket: WebSocket) -> int | None:
        return self.user_id_map.get(websocket)

    def check_rate_limit(self, websocket: WebSocket) -> bool:
        """Return False if the sender has exceeded their send rate."""
        bucket = self.rate_limiters.get(websocket)
        return bucket.consume() if bucket else True

    async def connect(self, websocket: WebSocket, username: str, is_account: bool, user_id: int | None, db_factory) -> None:
        await websocket.accept()
        self.active_connections[websocket] = username
        self.user_id_map[websocket] = user_id
        self.rate_limiters[websocket] = LeakyBucket()
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
        self.rate_limiters.pop(websocket, None)
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
