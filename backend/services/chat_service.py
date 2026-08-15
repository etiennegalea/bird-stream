import logging
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from litestar import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from models.orm import ChatMessage, User
from services.admin_action_service import record_admin_action
from services.profanity_service import record_profanities

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
        self.ip_map: dict[WebSocket, str | None] = {}
        self.blocked_ips: set[str] = set()

    def active_usernames(self) -> set[str]:
        return set(self.active_connections.values())

    def is_account_user(self, websocket: WebSocket) -> bool:
        return websocket in self.account_sockets

    def get_user_id(self, websocket: WebSocket) -> int | None:
        return self.user_id_map.get(websocket)

    def is_ip_blocked(self, ip: str | None) -> bool:
        return bool(ip and ip in self.blocked_ips)

    def check_rate_limit(self, websocket: WebSocket) -> bool:
        """Return False if the sender has exceeded their send rate."""
        bucket = self.rate_limiters.get(websocket)
        return bucket.consume() if bucket else True

    def get_connected_users(self) -> dict:
        """Return structured participant info for the admin panel."""
        accounts = []
        guests = []
        for ws, username in self.active_connections.items():
            ip = self.ip_map.get(ws)
            if ws in self.account_sockets:
                accounts.append({
                    "username": username,
                    "user_id": self.user_id_map.get(ws),
                    "ip": ip,
                })
            else:
                guests.append({"username": username, "ip": ip})
        accounts.sort(key=lambda x: x["username"])
        guests.sort(key=lambda x: x["username"])
        return {
            "accounts": accounts,
            "guests": guests,
            "blocked_ips": sorted(self.blocked_ips),
        }

    async def block_ip(self, ip: str) -> int:
        """Block an IP and close any matching active connections. Returns closed count."""
        self.blocked_ips.add(ip)
        to_close = [ws for ws, stored_ip in self.ip_map.items() if stored_ip == ip]
        for ws in to_close:
            try:
                await ws.close()
            except Exception:
                pass
            self.disconnect(ws)
        return len(to_close)

    async def disconnect_user(self, user_id: int) -> int:
        """Close every active chat connection belonging to an account."""
        to_close = [
            ws for ws, stored_user_id in self.user_id_map.items()
            if stored_user_id == user_id
        ]
        for ws in to_close:
            try:
                await ws.close(code=4403)
            except Exception:
                pass
            self.disconnect(ws)
        return len(to_close)

    def unblock_ip(self, ip: str) -> None:
        self.blocked_ips.discard(ip)

    async def connect(self, websocket: WebSocket, username: str, is_account: bool, user_id: int | None, db_factory, client_ip: str | None = None) -> None:
        await websocket.accept()
        self.active_connections[websocket] = username
        self.user_id_map[websocket] = user_id
        self.ip_map[websocket] = client_ip
        self.rate_limiters[websocket] = LeakyBucket()
        if is_account:
            self.account_sockets.add(websocket)
        logger.info(f"New chat connection. Total users: {len(self.active_connections)}")

        with db_factory() as session:
            rows = session.execute(
                select(ChatMessage)
                .options(joinedload(ChatMessage.user))
                .where(ChatMessage.is_deleted.is_(False))
                .order_by(ChatMessage.timestamp.desc())
                .limit(50)
            ).scalars().all()

        if rows:
            history = [
                {
                    "type": "message",
                    "id": m.id,
                    "sender_type": m.sender_type,
                    "username": (m.user.username if m.sender_type == "account" and m.user else m.username),
                    "user_id": m.user_id,
                    "avatar": (m.user.avatar if m.sender_type == "account" and m.user else None),
                    "is_account": m.sender_type == "account",
                    "text": m.text,
                    "timestamp": int(m.timestamp.timestamp() * 1000),
                    "is_deleted": False,
                }
                for m in reversed(rows)
            ]
            await websocket.send_json({"type": "history", "messages": history})

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.pop(websocket, None)
        self.account_sockets.discard(websocket)
        self.user_id_map.pop(websocket, None)
        self.rate_limiters.pop(websocket, None)
        self.ip_map.pop(websocket, None)
        logger.info(f"Chat connection removed. Total users: {len(self.active_connections)}")

    async def broadcast_participants(self) -> None:
        accounts = sorted(
            self.active_connections[ws]
            for ws in self.account_sockets
            if ws in self.active_connections
        )
        guests = sorted(
            username
            for ws, username in self.active_connections.items()
            if ws not in self.account_sockets
        )
        msg = {
            "type": "participants",
            "count": len(self.active_connections),
            "accounts": accounts,
            "guests": guests,
        }
        for ws in list(self.active_connections):
            try:
                await ws.send_json(msg)
            except Exception:
                pass

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
                stored_message = ChatMessage(
                    user_id=user_id,
                    username=message["username"],
                    sender_type=sender_type,
                    text=message["text"],
                    message_type="message",
                )
                session.add(stored_message)
                if sender_type == "account" and user_id:
                    record_profanities(session, user_id, message["text"])
                session.commit()
                message["id"] = stored_message.id
                message["is_deleted"] = False

        await self.broadcast_event(message)

    async def broadcast_event(self, event: dict[str, Any]) -> None:
        """Broadcast a chat event and discard dead sockets."""

        connections_to_remove = []
        for connection in self.active_connections:
            try:
                await connection.send_json(event)
            except Exception as e:
                logger.error(f"Error sending message to a client: {e}")
                connections_to_remove.append(connection)

        for connection in connections_to_remove:
            self.disconnect(connection)

    async def soft_delete_message(
        self, db_factory, message_id: int, admin_user_id: int
    ) -> tuple[dict | None, str]:
        """Hide a chat message, retain its text, audit it, and notify clients."""
        with db_factory() as session:
            message = session.get(ChatMessage, message_id)
            if not message:
                return None, "Message not found"
            if message.is_deleted:
                return None, "Message is already deleted"

            message.is_deleted = True
            message.deleted_at = datetime.now(timezone.utc)
            message.deleted_by_admin_id = admin_user_id
            record_admin_action(
                session,
                admin_user_id=admin_user_id,
                action_type="chat.message_deleted",
                target_type="chat_message",
                target_id=message.id,
                details={
                    "message_user_id": message.user_id,
                    "message_username": message.username,
                },
            )
            result = {
                "message_id": message.id,
                "user_id": message.user_id,
                "username": message.username,
                "deleted_at": message.deleted_at.isoformat(),
            }
            session.commit()

        await self.broadcast_event({"type": "message_deleted", **result})
        return result, ""
