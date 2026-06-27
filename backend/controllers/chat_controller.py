import json
import logging
from datetime import datetime

from litestar import WebSocket, websocket
from litestar.datastructures import State
from litestar.exceptions import WebSocketDisconnect

from services.chat_service import ChatService

logger = logging.getLogger("chat_controller")

chat_service = ChatService()


@websocket("/chat")
async def chat_endpoint(socket: WebSocket, state: State) -> None:
    raw_username = socket.query_params.get("username")
    username = raw_username[:20] if raw_username else "anon"

    await chat_service.connect(socket, state.db)
    logger.info(f"User {username} connected. Total users: {len(chat_service.active_connections)}")

    await chat_service.broadcast_message(
        {"type": "system", "text": f"{username} has joined the chat"},
        state.db,
    )

    try:
        while True:
            data = await socket.receive_text()

            try:
                message_data = json.loads(data)

                if "username" not in message_data or "text" not in message_data:
                    logger.warning(f"Received invalid message format: {message_data}")
                    continue

                msg_username = message_data["username"][:20]
                text = message_data["text"][:500]

                if not text.strip():
                    continue

                if msg_username != username:
                    logger.warning(f"Username mismatch: {msg_username} vs {username}")
                    msg_username = username

                await chat_service.broadcast_message(
                    {"type": "message", "username": msg_username, "text": text},
                    state.db,
                )
                logger.info(f"Message from {msg_username}: {text[:30]}...")

            except json.JSONDecodeError:
                logger.warning(f"Received invalid JSON: {data}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")

    except WebSocketDisconnect:
        await chat_service.disconnect(socket)
        await chat_service.broadcast_message(
            {"type": "system", "text": f"{username} has left the chat"},
            state.db,
        )
    except Exception as e:
        logger.error(f"Error in chat WebSocket endpoint: {e}")
        await chat_service.disconnect(socket)
