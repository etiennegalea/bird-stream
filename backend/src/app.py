from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import logging

from src.components.connection_manager import ConnectionManager
from src.components.video_stream import VideoStream


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backend | main")

manager = ConnectionManager()
vs = VideoStream(0)

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
    await manager.connect(websocket)
    logger.info(f"Active connections: {len(manager.active_connections)}")

    try:
        while True:
            async with vs.lock:
                frame_data = vs.global_frame_data

            if frame_data:
                # add viewer number to frame data
                frame_data['type'] = 'viewerCount'
                frame_data['viewers'] = len(manager.active_connections)
                # send
                await websocket.send_json(frame_data)

            # Send data at ~30 FPS to connected clients
            await asyncio.sleep(1 / 30)
    except WebSocketDisconnect:
        await manager.disconnect(websocket)

        # Notify remaining clients about updated viewer count
        if frame_data:
            frame_data['type'] = 'viewerCount'
            frame_data['viewers'] = len(manager.active_connections)
            await manager.broadcast(frame_data)
    except Exception as e:
        logger.error(f"Error in WebSocket endpoint: {e}")