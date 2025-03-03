from datetime import datetime
import logging
from aiortc import MediaStreamTrack, VideoStreamTrack
from av import VideoFrame
import cv2
import pytz
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder, MediaRelay
from aiortc.rtcrtpsender import RTCRtpSender

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("videostream")


class VideoTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()
        # self.camera = cv2.VideoCapture(0)
        self.camera = cv2.VideoCapture("/dev/video0")
        self.timezone = pytz.timezone('Europe/Amsterdam')
        logger.info("init video stream capture ...")

    async def recv(self):
        success, frame = self.camera.read()
        if not success:
            logger.error("Failed to capture frame from camera")
            return None

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

        # Convert to RGB for VideoFrame
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Create VideoFrame
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = video_frame.time = 0

        logger.info(f"video_frame: {video_frame}")

        return video_frame

    def stop(self):
        super().stop()
        self.camera.release()


def create_local_tracks(play_from=False, decode=True):
    global relay, webcam

    if play_from:
        player = MediaPlayer(play_from, decode=decode)
        return player.audio, player.video
    else:
        options = {"framerate": "30", "video_size": "640x480"}
        # webcam = MediaPlayer("default:none", format="avfoundation", options=options)
        webcam = MediaPlayer("/dev/video0", options=options)
        return None, webcam.video

def force_codec(pc, sender, forced_codec="video/H264"):
    kind = forced_codec.split("/")[0]
    codecs = RTCRtpSender.getCapabilities(kind).codecs
    transceiver = next(t for t in pc.getTransceivers() if t.sender == sender)
    transceiver.setCodecPreferences(
        [codec for codec in codecs if codec.mimeType == forced_codec]
    )
