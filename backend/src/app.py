from fastapi import FastAPI, Body, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay
from datetime import datetime
import asyncio
import logging
import json
import html

from src.components.connection_manager import ConnectionManager
from src.components.video_stream import create_local_tracks, force_codec
from src.components.chat_room import ChatRoom
from src.components.weather import fetch_weather_periodically, WEATHER_DATA
from src.models import ClientModel


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backend | main")

pcs_manager = ConnectionManager()
relay = MediaRelay()
chatroom = ChatRoom()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global video

    logger.info("Application is starting up...")
    audio, video = create_local_tracks()
    # audio, video = create_local_tracks("/app/media/birbs-of-paradise.mp4")

    asyncio.create_task(fetch_weather_periodically(cache_expiration=3600))

    yield
    
    # Shutdown: runs when the app is shutting down
    await pcs_manager.clean_up()
    logger.info("Application is shutting down...")
    print("shutdown")

    pcs_manager.clean_up()

app = FastAPI(
    title="LoaR Birb Stream",
    version="v1",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def print_pcs(pcs):
    print(":: ALL PCS ::")
    for key, value in pcs.items():
        print(f"key: {key}, value: {value}")

@app.post("/webrtc/offer")
async def offer(peer: ClientModel = Body(...)): 

    config = RTCConfiguration([
        RTCIceServer(urls=["stun:stun.l.google.com:19302", "stun:77.174.190.102:3478"]),
        RTCIceServer(urls=["turn:77.174.190.102:3478"], username="user", credential="supersecretpassword")
    ])
    
    pc = RTCPeerConnection(config)

    # store peer connection
    pcs_manager.add_peer(peer.id, pc)

    video_sender = pc.addTrack(relay.subscribe(video))
    print(f"video: {video}")
    print(f"video_sender: {video_sender}")

    @pc.on("track")
    def on_track(track):
        print("Received track:", track.kind)
        if track.kind == "video":
            print("Received video track!!")

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        if pc.iceConnectionState == "failed" or pc.iceConnectionState == "disconnected":
            try:
                print(f"ICE Connection failed for peer {peer.id}, cleaning up")
                await pcs_manager.remove_peer(peer.id, pc)
            except Exception as e:
                logger.error(f"Error (ICE) removing peer: {e}")

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state changed to {pc.connectionState} for peer {peer.id}")
        if pc.connectionState in ["closed", "failed", "disconnected"]:
            try:
                print(f"Cleaning up connection for peer {peer.id}")
                await pcs_manager.remove_peer(peer.id, pc)
            except Exception as e:
                logger.error(f"Error removing peer: {e}")

    
    # Set remote description only once
    await pc.setRemoteDescription(RTCSessionDescription(sdp=peer.offer.sdp, type=peer.offer.type))
    
    force_codec(pc, video_sender)

    # Create and set local description
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    }

@app.get("/webrtc/getpeers")
async def get_peers(verbose: bool = False):
    return pcs_manager.get_peers(verbose=verbose)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

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

    return {
        "data": WEATHER_DATA["data"],
        "last_updated": WEATHER_DATA["last_updated"]
    }
