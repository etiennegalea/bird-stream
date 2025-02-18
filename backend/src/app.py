from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
import json
import httpx
from pydantic import BaseModel

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

class OfferModel(BaseModel):
    sdp: str
    type: str

class ClientModel(BaseModel):
    name: str
    offer: OfferModel

def print_pcs():
    for pc in pcs:
        print(f"pc: {pc}")

@app.post("/webrtc/offer")
async def offer(client_request: ClientModel = Body(...)): 
    pc = RTCPeerConnection()
    if pc not in pcs:
        pcs.add(pc)

    print(" --> ALL PCS <--")
    for pc in pcs:
        print(f"pc: {pc}, name: {client_request.name}")

    _, video = vs.create_local_tracks()
    video_sender = pc.addTrack(video)
    
    # Set remote description only once
    await pc.setRemoteDescription(RTCSessionDescription(sdp=client_request.offer.sdp, type=client_request.offer.type))
    
    # Force codec settings if needed
    vs.force_codec(pc, video_sender)

    # Create and set local description
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("xxx Connection state is %s" % pc.connectionState)
        if pc.connectionState in ["closed", "failed"]:
            print("xxx Unresponsive peer, removing connection xxx")
            print(pc)
            await pc.close()
            pcs.discard(pc)
            print

        # Get track information
    # for transceiver in pc.getTransceivers():
    #     print(f"--> Track: {transceiver.sender.track}")

    print(f"--> current PC: {pc}")
    
    return {
        "sdp": pc.localDescription.sdp, 
        "type": pc.localDescription.type
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}
