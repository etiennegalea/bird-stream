from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
import asyncio
import logging
import json
import html

from src.components.connection_manager import ConnectionManager
from src.components.video_stream import VideoStream
from src.components.chat_room import ChatRoom
from src.components.weather import get_weather


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backend | main")

vs = VideoStream(0)
videoManager = ConnectionManager()
chatroom = ChatRoom()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    asyncio.create_task(vs.video_stream())
    yield

app = FastAPI(lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await videoManager.connect(websocket)
    logger.info(f"Active connections: {len(videoManager.active_connections)}")

    try:
        while True:
            async with vs.lock:
                frame_data = vs.global_frame_data

            if frame_data:
                # add viewer number to frame data
                frame_data['type'] = 'viewerCount'
                frame_data['viewers'] = len(videoManager.active_connections)
                # send
                await websocket.send_json(frame_data)

            # Send data at ~30 FPS to connected clients
            await asyncio.sleep(1 / 30)
    except WebSocketDisconnect:
        await videoManager.disconnect(websocket)

        # Notify remaining clients about updated viewer count
        if frame_data:
            frame_data['type'] = 'viewerCount'
            frame_data['viewers'] = len(videoManager.active_connections)
            await videoManager.broadcast(frame_data)
    except Exception as e:
        await videoManager.disconnect(websocket)
        
        logger.error(f"Error in WebSocket endpoint: {e}")

@app.websocket("/chat")
async def chat_endpoint(websocket: WebSocket):
    # Extract username from query parameters
    username = html.escape(websocket.query_params.get("username", "Anonymous"))[:20]
    
    await chatroom.connect(websocket)
    logger.info(f"User {username} connected to chat. Total chat users: {len(chatroom.active_connections)}")

    # Send a system message about the new user
    await chatroom.broadcast_message({
        "type": "system",
        "text": f"{username} has joined the chat",
        "timestamp": datetime.now().isoformat(' ')
    })

    try:
        while True:
            # Wait for messages from the client
            data = await websocket.receive_text()
            
            try:
                # Parse the message
                message_data = json.loads(data)
                
                # Validate message format
                if "username" not in message_data or "text" not in message_data:
                    logger.warning(f"Received invalid message format: {message_data}")
                    continue
                
                # Sanitize and limit message length
                msg_username = message_data["username"][:20]
                text = html.escape(message_data["text"])[:500]
                
                # Verify username matches the connected user
                if msg_username != username:
                    logger.warning(f"Username mismatch: {msg_username} vs {username}")
                    msg_username = username  # Force the correct username
                
                # Create the message object
                chat_message = {
                    "type": "message",
                    "username": msg_username,
                    "text": text,
                    "timestamp": message_data.get("timestamp", datetime.now().isoformat())
                }
                
                # Broadcast the message to all clients
                await chatroom.broadcast_message(chat_message)
                logger.info(f"Message from {msg_username}: {text[:30]}...")
                
            except json.JSONDecodeError:
                logger.warning(f"Received invalid JSON: {data}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                
    except WebSocketDisconnect:
        # disconnect the user first
        await chatroom.disconnect(websocket)
        # Send a system message about the user leaving
        await chatroom.broadcast_message({
            "type": "system",
            "text": f"{username} has left the chat",
            "timestamp": datetime.now().isoformat(' ')
        })
    except Exception as e:
        logger.error(f"Error in chat WebSocket endpoint: {e}")
        await chatroom.disconnect(websocket)

@app.get("/weather")
async def weather_endpoint():
    """Endpoint to get weather data for Rotterdam"""
    return await get_weather()
