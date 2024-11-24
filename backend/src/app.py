from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import cv2
import asyncio
import base64
from datetime import datetime
from typing import List
from time import time

app = FastAPI()

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


@app.get("/")
async def root():
    return {"message": "This works!"}


@app.websocket("/stream")
async def video_stream(websocket: WebSocket):
    await websocket.accept()
    async with lock:
        connected_clients.append(websocket)
    await broadcast_viewer_count()

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
            }

            await broadcast_frame(frame_data)

            await asyncio.sleep(1 / 30) # 30 fps

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await broadcast_viewer_count()

async def broadcast_viewer_count():
    async with lock:
        viewer_count = len(connected_clients)
    for client in connected_clients[:]:
        try:
            await client.send_json({"type": "viewerCount", "count": viewer_count})
        except Exception as e:
            print(f"Error sending viewer count: {e}")
            async with lock:
                connected_clients.remove(client)

async def broadcast_frame(frame_data):
    async with lock:
        for client in connected_clients[:]:
            try:
                await client.send_json(frame_data)
            except Exception as e:
                print(f"Error sending frame to a client: {e}")
                async with lock:
                    connected_clients.remove(client)
