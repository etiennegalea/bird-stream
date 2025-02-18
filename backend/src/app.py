from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
import json

from src.connection_manager import ConnectionManager
import src.video_stream as vs
from src.models import ClientModel


# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("backend")
manager = ConnectionManager()

print(manager)
pcs = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global video
    
    # Startup: runs before the app starts
    logger.info("Application is starting up...")
    _, video = vs.create_local_tracks()
    # Initialize resources here (database connections, caches, etc.)

    yield
    
    # Shutdown: runs when the app is shutting down
    logger.info("Application is shutting down...")
    print("shutdown")

    # Cleanup resources here (close connections, etc.)
    coros = [pc.close() for pc in pcs.values()]
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

def print_pcs(pcs):
    print(":: ALL PCS ::")
    for key, value in pcs.items():
        print(f"key: {key}, value: {value}")

@app.post("/webrtc/offer")
async def offer(peer: ClientModel = Body(...)): 
    pc = RTCPeerConnection()

    # store peer connection
    pcs[peer.id] = pc
    print_pcs(pcs)

    video_sender = pc.addTrack(video)
    
    # Set remote description only once
    await pc.setRemoteDescription(RTCSessionDescription(sdp=peer.offer.sdp, type=peer.offer.type))
    
    # Force codec settings if needed
    vs.force_codec(pc, video_sender)

    # Create and set local description
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("xxx Connection state is %s" % pc.connectionState)
        if pc.connectionState in ["closed", "failed"]:
            print(f"xxx Unresponsive peer, removing connection xxx {pc} xxx")
            await pc.close()
            pcs.pop(peer.id, None)

    print(f":: current PC: {pc} ::")
    print_pcs(pcs)
    
    return {
        "sdp": pc.localDescription.sdp, 
        "type": pc.localDescription.type
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}
