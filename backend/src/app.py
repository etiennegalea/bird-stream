from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import cv2
import asyncio
import logging
from typing import List
from av import VideoFrame
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder, MediaRelay
from aiortc.rtcrtpsender import RTCRtpSender
import pytz
from datetime import datetime
import json

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
        logger.info("init video stream capture ...")

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

        logger.info(f"video_frame: {video_frame}")

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

def create_local_tracks(play_from=False, decode=None):
    global relay, webcam

    if play_from:
        player = MediaPlayer(play_from, decode=decode)
        return player.audio, player.video
    else:
        options = {"framerate": "30", "video_size": "640x480"}
        if relay is None:
            webcam = MediaPlayer("/dev/video0", format="v4l2", options=options)
            relay = MediaRelay()
        return None, relay.subscribe(webcam.video)


def force_codec(pc, sender, forced_codec):
    kind = forced_codec.split("/")[0]
    codecs = RTCRtpSender.getCapabilities(kind).codecs
    transceiver = next(t for t in pc.getTransceivers() if t.sender == sender)
    transceiver.setCodecPreferences(
        [codec for codec in codecs if codec.mimeType == forced_codec]
    )

@app.post("/webrtc/offer")  # Changed from GET to POST
async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    # open media source
    # audio, video = create_local_tracks(
    #     args.play_from, decode=not args.play_without_decoding
    # )

    video = create_local_tracks()

    # if audio:
        # audio_sender = pc.addTrack(audio)
        # if args.audio_codec:
        #     force_codec(pc, audio_sender, args.audio_codec)
        # elif args.play_without_decoding:
        #     raise Exception("You must specify the audio codec using --audio-codec")

    if video:
        video_sender = pc.addTrack(video)
        force_codec(pc, video_sender, args.video_codec)
        # elif args.play_without_decoding:
        #     raise Exception("You must specify the video codec using --video-codec")

    await pc.setRemoteDescription(offer)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})

pcs = set()

async def on_shutdown():
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

@app.get("/health")
async def health_check():
    return {"status": "ok"}