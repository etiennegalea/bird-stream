from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import cv2
import time
from datetime import datetime


app = FastAPI()

# enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the USB camera
camera = cv2.VideoCapture(0)  # Change index if needed

def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            break

        # Get the current date and time
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        # Get frame dimensions
        height, width, _ = frame.shape

        # Set position for the bottom-left corner
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.8
        color = (255, 255, 255)  # White color in BGR
        thickness = 1

        # Calculate position dynamically
        text_size = cv2.getTextSize(timestamp, font, font_scale, thickness)[0]
        text_x = 10  # 10 pixels from the left
        text_y = height - 10  # 10 pixels from the bottom
        position = (text_x, text_y)

        # Add the timestamp to the frame
        cv2.putText(frame, timestamp, position, font, font_scale, color, thickness, cv2.LINE_AA)

        # Encode the frame as JPEG
        _, encoded_frame = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + encoded_frame.tobytes() + b"\r\n")

        time.sleep(0.03)  # ~30 frames per second (adjust as needed)

@app.get("/")
async def root():
    return {"message": "Camera stream available at /stream"}

@app.get("/stream")
async def stream():
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers=headers
    )
