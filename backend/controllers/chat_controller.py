import json
import logging
from time import time as _time

from litestar import WebSocket, get, websocket
from litestar.datastructures import State
from litestar.exceptions import WebSocketDisconnect

import services.auth_service as auth_svc
from services.chat_service import ChatService

logger = logging.getLogger("chat_controller")

chat_service = ChatService()


def _validate_token(token: str, username: str) -> tuple[bool, int | None]:
    if not token:
        return False, None
    payload = auth_svc.decode_jwt(token)
    if not payload or payload.get("username") != username:
        return False, None
    return True, int(payload["sub"])


async def _process_incoming(data: str, username: str, socket: WebSocket, db_factory) -> None:
    try:
        message_data = json.loads(data)
    except json.JSONDecodeError:
        logger.warning(f"Received invalid JSON: {data}")
        return

    if "username" not in message_data or "text" not in message_data:
        logger.warning(f"Received invalid message format: {message_data}")
        return

    msg_username = message_data["username"][:20]
    text = message_data["text"][:500]

    if not text.strip():
        return

    if not chat_service.check_rate_limit(socket):
        await socket.send_json({"type": "system", "text": "You're sending messages too quickly. Slow down.", "timestamp": int(_time() * 1000)})
        return

    if msg_username != username:
        logger.warning(f"Username mismatch: {msg_username} vs {username}")
        msg_username = username

    is_acct = chat_service.is_account_user(socket)
    await chat_service.broadcast_message(
        {
            "type": "message",
            "username": msg_username,
            "text": text,
            "is_account": is_acct,
            "user_id": chat_service.get_user_id(socket),
            "sender_type": "account" if is_acct else "guest",
        },
        db_factory,
    )
    logger.info(f"Message from {msg_username}: {text[:30]}...")


@get("/chat/usernames", sync_to_thread=False)
def chat_usernames() -> list[str]:
    return sorted(chat_service.active_usernames())


@websocket("/chat")
async def chat_endpoint(socket: WebSocket, state: State) -> None:
    raw_username = socket.query_params.get("username")
    username = raw_username[:20] if raw_username else "anon"
    is_account, user_id = _validate_token(socket.query_params.get("token", ""), username)

    await chat_service.connect(socket, username, is_account, user_id, state.db)
    logger.info(f"User {username} connected. Total users: {len(chat_service.active_connections)}")

    await chat_service.broadcast_message(
        {"type": "system", "text": f"{username} has joined the chat"},
        state.db,
    )

    try:
        while True:
            data = await socket.receive_text()
            try:
                await _process_incoming(data, username, socket, state.db)
            except Exception as e:
                logger.exception(f"Error processing message: {e}")

    except WebSocketDisconnect:
        await chat_service.disconnect(socket)
        await chat_service.broadcast_message(
            {"type": "system", "text": f"{username} has left the chat"},
            state.db,
        )
    except Exception as e:
        logger.exception(f"Error in chat WebSocket endpoint: {e}")
        await chat_service.disconnect(socket)
