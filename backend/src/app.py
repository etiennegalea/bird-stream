from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
import json
import httpx

from src.connection_manager import ConnectionManager
import src.video_stream as vs

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("backend")
manager = ConnectionManager()

print(manager)
pcs = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: runs before the app starts
    logger.info("Application is starting up...")
    # Initialize resources here (database connections, caches, etc.)

    yield
    # async with httpx.AsyncClient() as client:
    #     yield {"client": client}
    
    # Shutdown: runs when the app is shutting down
    logger.info("Application is shutting down...")
    print("shutdown")

    # Cleanup resources here (close connections, etc.)
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

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

@app.post("/webrtc/offer")  # Changed from GET to POST
async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()

    print(pc)


    pcs.add()

    print(pcs)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    video = vs.create_local_tracks()
    video_sender = pc.addTrack(video)

    vs.force_codec(pc, video_sender)
    await pc.setRemoteDescription(offer)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})


@app.get("/health")
async def health_check():
    return {"status": "ok"}
