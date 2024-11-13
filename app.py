from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import cv2

app = FastAPI()

# Initialize the USB camera
camera = cv2.VideoCapture(0)  # Change index if needed

def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            break
        _, encoded_frame = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + encoded_frame.tobytes() + b'\r\n')

# @app.get("/")
# async def root():
#     return {"message": "Camera stream available at /stream"}

@app.get("/")
async def stream():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")
