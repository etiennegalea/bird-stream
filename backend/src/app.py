from fastapi import FastAPI
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

class VideoStreamTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, device_id=0):
        super().__init__()
        self.camera = cv2.VideoCapture(device_id)
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

@asynccontextmanager
async def lifespan(app: FastAPI):
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

@app.get("/webrtc/offer")
async def webrtc_offer():
    video_track = VideoStreamTrack()
    
    pc = RTCPeerConnection()
    pc.addTrack(video_track)
    
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

@app.post("/webrtc/answer")
async def webrtc_answer(session_description: dict):
    answer = RTCSessionDescription(sdp=session_description["sdp"], type=session_description["type"])
    await pc.setRemoteDescription(answer)
    return {"status": "success"}
