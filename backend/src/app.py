from fastapi import FastAPI, Body, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay
from aiortc.rtcrtpsender import RTCRtpSender
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
from src.utils import load_turn_credentials


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backend | main")

pcs_manager = ConnectionManager()
relay = MediaRelay()
chatroom = ChatRoom()

# Add a new connection manager for peer count WebSocket connections
peer_count_manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global audio, video

    logger.info("Application is starting up...")
    audio, video = create_local_tracks(enable_audio=False)
    # audio, video = create_local_tracks("/app/media/birbs-of-paradise.mp4")

    asyncio.create_task(fetch_weather_periodically(cache_expiration=3600))
    
    # Increase port range for better connectivity
    RTCRtpSender.TRANSPORT_POOL_SIZE = 1000
    RTCRtpSender.TRANSPORT_PORT_MIN = 49152
    RTCRtpSender.TRANSPORT_PORT_MAX = 65535

    yield
    
    # Shutdown: runs when the app is shutting down
    await pcs_manager.clean_up()
    logger.info("Application is shutting down...")

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

    user, password = load_turn_credentials()

    config = RTCConfiguration([
        # Add multiple STUN servers for better NAT traversal
        RTCIceServer(urls=[
            "stun:stun.l.google.com:19302" # Google STUN server fallback
        ]),
        # TURN server configuration with both IPv4 and IPv6 support
        RTCIceServer(
            urls=[
                # # "turn:global.relay.metered.ca:80",
                # # "turn:global.relay.metered.ca:80?transport=tcp",
                # "turn:global.relay.metered.ca:80?transport=udp",
                # # "turn:global.relay.metered.ca:443",
                # # "turns:global.relay.metered.ca:443?transport=tcp",
                # "turn:global.relay.metered.ca:443?transport=udp"
                "turn:turn.lifeofarobin.com:3478?transport=udp",
                "turns:turn.lifeofarobin.com:5349?transport=udp"
            ],
            username="user",
            credential="supersecretpassword"
            # username=user,
            # credential=password
        )
    ])
    
    # Configure for both IPv4 and IPv6
    config.iceTransportPolicy = "all"
    config.bundlePolicy = "max-bundle"
    config.rtcpMuxPolicy = "require"
    # config.iceTransportPolicy = "relay"

    pc = RTCPeerConnection(config)

    # store peer connection
    pcs_manager.add_peer(peer.id, pc)

    # Add both audio and video tracks
    if audio:
        audio_sender = pc.addTrack(relay.subscribe(audio))
        logger.info(f"Audio sender created: {audio_sender}")
        force_codec(pc, audio_sender, "audio/opus")  # Force Opus codec for audio

    video_sender = pc.addTrack(relay.subscribe(video))
    logger.info(f"Video sender created: {video_sender}")
    force_codec(pc, video_sender, "video/H264")  # Force H264 codec for video

    @pc.on("track")
    def on_track(track):
        logger.info(f"Received track: {track.kind}")
        if track.kind == "video":
            logger.info("Received video track!!")
        elif track.kind == "audio":
            logger.info("Received audio track!!")

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        logger.info(f"ICE connection state changed to: {pc.iceConnectionState}")
        if pc.iceConnectionState == "failed" or pc.iceConnectionState == "disconnected":
            try:
                logger.info(f"ICE Connection failed for peer {peer.id}, cleaning up")
                await pcs_manager.remove_peer(peer.id, pc)
            except Exception as e:
                logger.error(f"Error (ICE) removing peer: {e}")

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"Connection state changed to {pc.connectionState} for peer {peer.id}")
        if pc.connectionState in ["closed", "failed", "disconnected"]:
            try:
                logger.info(f"Cleaning up connection for peer {peer.id}")
                await pcs_manager.remove_peer(peer.id, pc)
            except Exception as e:
                logger.error(f"Error removing peer: {e}")

    @pc.on("icecandidate")
    def on_icecandidate(candidate):
        logger.info(f"New ICE candidate: {candidate}")

    # Set remote description only once
    await pc.setRemoteDescription(RTCSessionDescription(sdp=peer.offer.sdp, type=peer.offer.type))
    
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

@app.get("/webrtc/config")
async def get_webrtc_config():
    """Return the current WebRTC port configuration"""
    return {
        "pool_size": RTCRtpSender.TRANSPORT_POOL_SIZE,
        "port_min": RTCRtpSender.TRANSPORT_PORT_MIN,
        "port_max": RTCRtpSender.TRANSPORT_PORT_MAX,
        "port_range": RTCRtpSender.TRANSPORT_PORT_MAX - RTCRtpSender.TRANSPORT_PORT_MIN + 1
    }

@app.websocket("/peer-count")
async def peer_count_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("New peer count WebSocket connection")
    
    try:
        while True:
            # Get current peer count
            peer_count = len(pcs_manager.get_peers())
            # Send the count to the client
            await websocket.send_json({"count": peer_count})
            # Wait for 5 seconds before sending the next update
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        logger.info("Peer count WebSocket disconnected")
    except Exception as e:
        logger.error(f"Error in peer count WebSocket: {e}")
