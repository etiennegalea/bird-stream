from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import cv2
import asyncio
import base64
from datetime import datetime
from typing import List
from time import time
import logging

from connection_manager import ConnectionManager

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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# init vars
camera = cv2.VideoCapture(0) # fetch first camera
connected_clients: List[WebSocket] = []
lock = asyncio.Lock()  # For thread-safe client list modifications
global_frame_data = None


@app.get("/")
async def root():
    return {"message": "This works!"}

@app.get("/stream")
def connect_to_stream(websocket: WebSocket):
    manager.connect(websocket)

    try:
        prev_timeframe = global_frame_data.timeframe
        while True:
            if global_frame_data.timeframe > prev_timeframe:
                websocket.send_json(global_frame_data)
                prev_timeframe = global_frame_data.timeframe
    except WebSocketDisconnect:
        logger.error(f"active_connections (disconnect) -- {manager.active_connections}")
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Exception: {e}")

@staticmethod
def video_stream():
    """
    Serve stream.
    """

    try:
        last_frame_time = time()
        while True:
            success, frame = camera.read()
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

            global_frame_data = frame_data

    except Exception as e:
        logger.error(f"Error: {e}")

# start stream
video_stream()

async def broadcast_viewer_count():
    for client in manager.active_connections[:]:
        await client.send_json({"type": "viewerCount", "count": manager.count_connections()})

async def broadcast_frame():
    for client in manager.active_connections[:]:
        await client.send_json(global_frame_data)