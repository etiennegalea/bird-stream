"""Viewer count over WebSocket, sourced from the MediaMTX control API.

Viewers connect to MediaMTX (WHEP/HLS), not to this backend, so the count
comes from polling /v3/paths/list and summing readers across all camera paths.
"""

import asyncio
import logging
import os

import aiohttp
from litestar import WebSocket, websocket
from litestar.exceptions import WebSocketDisconnect

logger = logging.getLogger("peer_count_controller")

MEDIAMTX_API_URL = os.environ.get("MEDIAMTX_API_URL", "http://mediamtx:9997")
MEDIAMTX_PATH = os.environ.get("MEDIAMTX_PATH", "birdcam")
POLL_INTERVAL = float(os.environ.get("PEER_COUNT_POLL_SECONDS", "3"))


async def get_viewer_count(session: aiohttp.ClientSession) -> int:
    try:
        async with session.get(
            f"{MEDIAMTX_API_URL}/v3/paths/list",
            timeout=aiohttp.ClientTimeout(total=2),
        ) as resp:
            if resp.status != 200:  # 404 = path not active (Pi offline)
                return 0
            data = await resp.json()
            paths = data.get("items", [])
            return sum(
                len(path.get("readers", []))
                for path in paths
                if path.get("name") == MEDIAMTX_PATH
                or path.get("name", "").startswith(f"{MEDIAMTX_PATH}-")
            )
    except Exception as e:
        logger.debug(f"MediaMTX API poll failed: {e}")
        return 0


@websocket("/peer-count")
async def peer_count_endpoint(socket: WebSocket) -> None:
    await socket.accept()
    logger.info("New peer count WebSocket connection")

    async def _send_loop() -> None:
        last = None
        async with aiohttp.ClientSession() as session:
            while True:
                count = await get_viewer_count(session)
                if count != last:
                    await socket.send_json({"count": count})
                    last = count
                await asyncio.sleep(POLL_INTERVAL)

    send_task = asyncio.create_task(_send_loop())
    try:
        await socket.receive_text()  # blocks until client disconnects
    except WebSocketDisconnect:
        logger.info("Peer count WebSocket disconnected")
    except Exception as e:
        logger.exception(f"Error in peer count WebSocket: {e}")
    finally:
        send_task.cancel()
        await asyncio.gather(send_task, return_exceptions=True)
