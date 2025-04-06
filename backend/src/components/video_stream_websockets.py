from datetime import datetime
import pytz
import cv2
import base64
import asyncio
from time import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backend | video_stream")


class VideoStream:
    def __init__(self, device_id=0):
        self.camera = cv2.VideoCapture(device_id)
        self.global_frame_data = None
        self.lock = asyncio.Lock()
        self.running = True
        self.timezone = pytz.timezone('Europe/Amsterdam')  # UTC+1 timezone

    async def cleanup(self):
        self.running = False
        if self.camera:
            self.camera.release()
        logger.info("Camera resources released")

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
                local_time = datetime.now(self.timezone)
                timestamp = local_time.strftime("%Y-%m-%d %H:%M:%S")
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

                # Limit FPS to ~30 video generation
                await asyncio.sleep(1 / 30)
        except Exception as e:
            logger.error(f"Error in video stream: {e}")
        finally:
            await self.cleanup()