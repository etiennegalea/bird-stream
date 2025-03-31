from fastapi import WebSocket
import logging
import json
from datetime import datetime
from typing import List, Dict, Any


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backend | chat_room")

class ChatRoom:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.chat_history: List[Dict[str, Any]] = []
        self.max_history = 50  # Store last 50 messages

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New chat connection. Total chat users: {len(self.active_connections)}")
        
        # Send chat history to new user
        if self.chat_history:
            await websocket.send_json({
                "type": "history",
                "messages": self.chat_history
            })

    async def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Chat connection removed. Total chat users: {len(self.active_connections)}")

    async def broadcast_message(self, message: Dict[str, Any]):
        # Add timestamp to message
        message["timestamp"] = int(datetime.now().timestamp() * 1000)
        if message["type"] != "system":
            self.chat_history.append(message)
        
        # Trim history if needed
        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history:]
        
        # Broadcast to all connected clients
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to a client: {e}")
                await self.disconnect(connection)
