from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import cv2
import asyncio
import logging
from typing import List
from av import VideoFrame
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder
import pytz
from datetime import datetime

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("backend")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("New connection established. Total: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info("Connection removed. Total: %d", len(self.active_connections))

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending data to a client: {e}")
                await self.disconnect(connection)

class VideoStreamTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()
        self.camera = cv2.VideoCapture("/dev/video0")
        self.timezone = pytz.timezone('Europe/Amsterdam')

    async def recv(self):
        success, frame = self.camera.read()
        if not success:
            logger.error("Failed to capture frame from camera")
            return None

        # Add timestamp to the frame
        local_time = datetime.now(self.timezone)
        timestamp = local_time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(
            frame, 
            timestamp, 
            (10, frame.shape[0] - 10), 
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.7, 
            (255, 255, 255), 
            1, 
            cv2.LINE_AA
        )

        # Convert to RGB for VideoFrame
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Create VideoFrame
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = video_frame.time = 0

        return video_frame

    def stop(self):
        super().stop()
        self.camera.release()

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: runs before the app starts
    logger.info("Application is starting up...")
    # Initialize resources here (database connections, caches, etc.)
    
    yield  # The application runs here
    
    # Shutdown: runs when the app is shutting down
    logger.info("Application is shutting down...")
    # Cleanup resources here (close connections, etc.)

app = FastAPI(lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Store active peer connections
pcs = set()

@app.post("/webrtc/offer")  # Changed from GET to POST
async def webrtc_offer(session_description: dict):  # Add parameter to receive offer
    video_track = VideoStreamTrack()
    
    pc = RTCPeerConnection()
    pcs.add(pc)  # Keep track of peer connection
    pc.addTrack(video_track)
    
    # Set the remote description from client's offer
    offer = RTCSessionDescription(sdp=session_description["sdp"], type=session_description["type"])
    await pc.setRemoteDescription(offer)
    
    # Create and set local description
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    # Clean up when connection closes
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            pcs.discard(pc)
            await pc.close()
    
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

@app.get("/health")
async def health_check():
    return {"status": "ok"}