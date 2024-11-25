from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import cv2
import asyncio
import base64
from datetime import datetime
from typing import List
from time import time
import logging

# from connection_manager import ConnectionManager

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        logger.error(f"active_connections (connect) -- {self.active_connections}")
        self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        logger.error(f"active_connections (disconnect) -- {self.active_connections}")
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

    def count_connections(self):
        return len(self.active_connections)


class VideoStream(device_id=0):
    def __init__(self, device_id):
        self.global_frame_data = None
        self.camera = cv2.VideoCapture(device_id)
        self.connected_clients: List[WebSocket] = []
        self.lock = asyncio.Lock()  # For thread-safe client list modifications

    @staticmethod
    def video_stream(self):
        """
        Serve stream.
        """

        try:
            last_frame_time = time()
            while True:
                success, frame = self.camera.read()
                if not success:
                    break

                # calculate FPS
                current_time = time()
                fps = 1 / max((current_time - last_frame_time), 1e-6)
                last_frame_time = current_time

                # add datetime
                now = datetime.now().astimezone()
                timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
                font = cv2.FONT_HERSHEY_SIMPLEX
                position = (10, frame.shape[0] - 10)
                cv2.putText(frame, timestamp, position, font, 0.7, (255, 255, 255), 1, cv2.LINE_AA)

                # encode frame and prepare json
                _, encoded_frame = cv2.imencode(".jpg", frame)
                frame_data = {
                    "type": "video",
                    "frame": base64.b64encode(encoded_frame).decode('utf-8'),
                    "fps": round(fps, 2),
                    "timestamp": timestamp
                }

                self.global_frame_data = frame_data

        except Exception as e:
            logger.error(f"Error: {e}")


# ========================================================================================== #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ],
)

logger = logging.getLogger("backend")
app = FastAPI()
manager = ConnectionManager()
vs = VideoStream(0)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

vs.video_stream()   # start stream

@app.get("/")
async def root():
    return {"message": "This works!"}

@app.get("/stream")
def connect_to_stream(websocket: WebSocket):
    manager.connect(websocket)

    try:
        prev_timeframe = vs.global_frame_data.timeframe
        while True:
            if vs.global_frame_data.timeframe > prev_timeframe:
                websocket.send_json(vs.global_frame_data)
                prev_timeframe = vs.global_frame_data.timeframe
    except WebSocketDisconnect:
        logger.error(f"active_connections (disconnect) -- {manager.active_connections}")
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Exception: {e}")

async def broadcast_viewer_count():
    for client in manager.active_connections[:]:
        await client.send_json({"type": "viewerCount", "count": manager.count_connections()})

async def broadcast_frame():
    for client in manager.active_connections[:]:
        await client.send_json(vs.global_frame_data)
