"""Live viewer count.

Each browser already keeps this WebSocket open. It reports whether its selected
player is connected, allowing us to count viewers rather than MediaMTX readers
(which can include internal detection readers and multiple camera sessions).
"""

import asyncio
import json
import logging

from litestar import WebSocket, websocket
from litestar.exceptions import WebSocketDisconnect

logger = logging.getLogger("peer_count_controller")


class ViewerRegistry:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()
        self.viewers: set[WebSocket] = set()

    @property
    def count(self) -> int:
        return len(self.viewers)

    def connect(self, socket: WebSocket) -> None:
        self.connections.add(socket)

    def set_viewing(self, socket: WebSocket, viewing: bool) -> bool:
        before = self.count
        if viewing:
            self.viewers.add(socket)
        else:
            self.viewers.discard(socket)
        return self.count != before

    def disconnect(self, socket: WebSocket) -> bool:
        before = self.count
        self.connections.discard(socket)
        self.viewers.discard(socket)
        return self.count != before


viewer_registry = ViewerRegistry()


async def _broadcast_count() -> None:
    if not viewer_registry.connections:
        return
    payload = {"count": viewer_registry.count}
    sockets = list(viewer_registry.connections)
    results = await asyncio.gather(
        *(socket.send_json(payload) for socket in sockets),
        return_exceptions=True,
    )
    stale = [
        socket
        for socket, result in zip(sockets, results)
        if isinstance(result, Exception)
    ]
    for socket in stale:
        viewer_registry.disconnect(socket)


@websocket("/peer-count")
async def peer_count_endpoint(socket: WebSocket) -> None:
    await socket.accept()
    viewer_registry.connect(socket)
    await socket.send_json({"count": viewer_registry.count})
    logger.info("Viewer presence connected")

    try:
        while True:
            raw = await socket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if viewer_registry.set_viewing(socket, data.get("viewing") is True):
                await _broadcast_count()
    except WebSocketDisconnect:
        logger.info("Viewer presence disconnected")
    except Exception as exc:
        logger.debug("Viewer presence socket closed: %s", exc)
    finally:
        changed = viewer_registry.disconnect(socket)
        if changed:
            await _broadcast_count()
