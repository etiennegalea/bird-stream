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

    change_event = asyncio.Event()

    def on_peer_change() -> None:
        change_event.set()

    pcs_manager.on_change(on_peer_change)

    async def _send_loop() -> None:
        try:
            while True:
                await socket.send_json({"count": len(pcs_manager.get_peers())})
                # Block until a peer is added/removed, or 5 s pass (fallback refresh).
                try:
                    await asyncio.wait_for(change_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                change_event.clear()
        except Exception:
            pass

    send_task = asyncio.create_task(_send_loop())
    try:
        await socket.receive_text()  # blocks until client disconnects
    except WebSocketDisconnect:
        logger.info("Peer count WebSocket disconnected")
    except Exception as e:
        logger.exception(f"Error in peer count WebSocket: {e}")
    finally:
        pcs_manager.remove_change_listener(on_peer_change)
        send_task.cancel()
        await asyncio.gather(send_task, return_exceptions=True)
