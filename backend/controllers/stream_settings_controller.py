"""Public (read-only) stream settings endpoints.

Every viewer needs to know whether video/audio are currently enabled so the
player can enforce blocks (forced mute, video-disabled overlay). Writing the
settings is admin-only and lives in the AdminController.
"""

import asyncio
import logging

from litestar import WebSocket, get, websocket
from litestar.exceptions import WebSocketDisconnect

from services.mqtt_service import mqtt_devices
from services.stream_settings_service import stream_settings

logger = logging.getLogger("stream_settings_controller")

WS_POLL_INTERVAL = 1.0


@get("/stream/settings")
async def get_stream_settings() -> dict:
    return stream_settings.snapshot()


@get("/stream/catalog")
async def get_stream_catalog() -> dict:
    """Enabled camera streams reported by all connected Pi transmitters."""
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
