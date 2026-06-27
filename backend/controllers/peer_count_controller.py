import asyncio
import logging

from litestar import WebSocket, websocket
from litestar.exceptions import WebSocketDisconnect

from services.webrtc_service import pcs_manager

logger = logging.getLogger("peer_count_controller")


@websocket("/peer-count")
async def peer_count_endpoint(socket: WebSocket) -> None:
    await socket.accept()
    logger.info("New peer count WebSocket connection")

    async def _send_loop() -> None:
        try:
            while True:
                peer_count = len(pcs_manager.get_peers())
                await socket.send_json({"count": peer_count})
                await asyncio.sleep(2)
        except Exception:
            pass

    send_task = asyncio.create_task(_send_loop())
    try:
        await socket.receive_text()  # blocks until client disconnects
    except WebSocketDisconnect:
        logger.info("Peer count WebSocket disconnected")
    except Exception as e:
        logger.error(f"Error in peer count WebSocket: {e}")
    finally:
        send_task.cancel()
        await asyncio.gather(send_task, return_exceptions=True)
