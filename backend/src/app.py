from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import cv2
import asyncio
import base64
from datetime import datetime
import logging
from typing import List
from time import time

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

class VideoStream:
    def __init__(self, device_id=0):
        self.camera = cv2.VideoCapture(device_id)
        self.global_frame_data = None
        self.lock = asyncio.Lock()

    async def video_stream(self):
        try:
            last_frame_time = time()
            while True:
                success, frame = self.camera.read()
                if not success:
                    logger.error("Failed to capture frame from camera")
                    break

                # Calculate FPS
                current_time = time()
                fps = 1 / max((current_time - last_frame_time), 1e-6)
                last_frame_time = current_time

                # Add timestamp to the frame
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

                # Encode the frame as JPEG
                _, encoded_frame = cv2.imencode(".jpg", frame)

                # Update global frame data
                async with self.lock:
                    self.global_frame_data = {
                        "type": "video",
                        "frame": base64.b64encode(encoded_frame).decode("utf-8"),
                        "fps": round(fps, 2),
                        "timestamp": timestamp
                    }

                # Limit FPS to ~30
                # await asyncio.sleep(1 / 30)
        except Exception as e:
            logger.error(f"Error in video stream: {e}")

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

    try:
        while True:
            async with vs.lock:
                frame_data = vs.global_frame_data

            if frame_data:
                # add viewer number to frame data
                frame_data['viewers'] = manager.active_connections
                # send
                await websocket.send_json(frame_data)

            # await asyncio.sleep(1 / 30)  # Send data at ~30 FPS
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Error in WebSocket endpoint: {e}")