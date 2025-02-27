from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay


from src.connection_manager import ConnectionManager
import src.video_stream as vs
from src.models import ClientModel

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("backend")
pcs_manager = ConnectionManager()
relay = MediaRelay()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global video
    # Startup: runs before the app starts
    logger.info("Application is starting up...")
    audio, video = vs.create_local_tracks()

    # Initialize resources here (database connections, caches, etc.)

    yield
    
    # Shutdown: runs when the app is shutting down
    await pcs_manager.clean_up()
    logger.info("Application is shutting down...")
    print("shutdown")

    # Cleanup resources here (close connections, etc.)
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
    pc = RTCPeerConnection()

    # store peer connection
    pcs_manager.add_peer(peer.id, pc)

    video_sender = pc.addTrack(relay.subscribe(video.video))
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
    
    vs.force_codec(pc, video_sender)

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
