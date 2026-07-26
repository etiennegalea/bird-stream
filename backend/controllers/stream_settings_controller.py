"""Public (read-only) stream settings endpoints.

Every viewer needs to know whether video/audio are currently enabled so the
player can enforce blocks (forced mute, video-disabled overlay). Writing the
settings is admin-only and lives in the AdminController.
"""

import asyncio
import logging

from litestar import WebSocket, get, websocket
from litestar.connection import Request
from litestar.datastructures import State
from litestar.exceptions import WebSocketDisconnect

import services.auth_service as auth_svc
from models.orm import User
from services.mqtt_service import mqtt_devices
from services.stream_settings_service import stream_settings

logger = logging.getLogger("stream_settings_controller")

WS_POLL_INTERVAL = 1.0


@get("/stream/settings")
async def get_stream_settings() -> dict:
    return stream_settings.snapshot()


def _request_is_admin(request: Request, db_factory) -> bool:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return False
    payload = auth_svc.decode_jwt(header[7:])
    if not payload:
        return False
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return False
    with db_factory() as session:
        user = session.get(User, user_id)
        return bool(user and user.is_admin)


@get("/stream/catalog")
async def get_stream_catalog(request: Request, state: State) -> dict:
    """Enabled camera streams reported by all connected Pi transmitters."""
    if stream_settings.private_enabled and not _request_is_admin(
        request, state.db
    ):
        return {"streams": []}
    return {"streams": mqtt_devices.stream_catalog()}


@websocket("/stream-settings")
async def stream_settings_endpoint(socket: WebSocket) -> None:
    """Push the current settings on connect, then on every change."""
    await socket.accept()

    async def _send_loop() -> None:
        last_version = None
        while True:
            if stream_settings.version != last_version:
                await socket.send_json(stream_settings.snapshot())
                last_version = stream_settings.version
            await asyncio.sleep(WS_POLL_INTERVAL)

    send_task = asyncio.create_task(_send_loop())
    try:
        await socket.receive_text()  # blocks until client disconnects
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception(f"Error in stream settings WebSocket: {e}")
    finally:
        send_task.cancel()
        await asyncio.gather(send_task, return_exceptions=True)
