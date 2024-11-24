from fastapi import WebSocket, WebSocketDisconnect
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ],
)

logger = logging.getLogger("connection_manager")

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        logger.error(f"active_connections (connect) -- {self.active_connections}")
        self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        logger.error(f"active_connections (disconnect) -- {self.active_connections}")
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

    def count_connections(self):
        return len(self.active_connections)