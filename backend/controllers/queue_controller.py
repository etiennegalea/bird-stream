import asyncio
import logging

from litestar import WebSocket, websocket
from litestar.datastructures import State
from litestar.exceptions import WebSocketDisconnect

from services.queue_service import QueueService, _READY

logger = logging.getLogger("queue_controller")


async def _stream_queue_updates(socket: WebSocket, svc: QueueService, ch: "asyncio.Queue[int]") -> None:
    pos = svc.position_of(ch)
    await socket.send_json({"type": "queued", "position": pos, "max_viewers": svc.max_viewers})

    while True:
        value = await _next_position(ch)
        if value is None:
            pos = svc.position_of(ch)
            if pos > 0:
                await socket.send_json({"type": "queued", "position": pos, "max_viewers": svc.max_viewers})
        elif value == _READY:
            await socket.send_json({"type": "ready", "max_viewers": svc.max_viewers})
            return
        else:
            await socket.send_json({"type": "queued", "position": value, "max_viewers": svc.max_viewers})


async def _next_position(ch: "asyncio.Queue[int]") -> "int | None":
    """Wait for a position update. Returns None on 15 s heartbeat timeout."""
    try:
        return await asyncio.wait_for(ch.get(), timeout=15.0)
    except asyncio.TimeoutError:
        return None


@websocket("/queue")
async def queue_endpoint(socket: WebSocket, state: State) -> None:
    await socket.accept()
    svc = state.queue_service

    if svc.slot_available():
        svc.reserve()
        try:
            await socket.send_json({"type": "ready", "max_viewers": svc.max_viewers})
            await socket.receive_text()
        except Exception:
            pass
        finally:
            svc.release()
        return

    ch = svc.enqueue()
    send_task = asyncio.create_task(_stream_queue_updates(socket, svc, ch))
    try:
        await socket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        send_task.cancel()
        await asyncio.gather(send_task, return_exceptions=True)
        svc.dequeue(ch)
