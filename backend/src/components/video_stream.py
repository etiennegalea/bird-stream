from datetime import datetime
import logging
import sys
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

        # logger.info(f"video_frame: {video_frame}")

        return video_frame

    def stop(self):
        super().stop()
        self.camera.release()


def create_local_tracks(play_from=False, decode=True, enable_audio=False):
    global relay, webcam

    if play_from:
        player = MediaPlayer(play_from, decode=decode)
        return player.audio if enable_audio else None, player.video
    else:
        options = {
            "framerate": "30",              # 30fps is smoother; 24fps can cause motion blur
            "video_size": "640x360",        # Try 360p first — less data to process, still decent quality
            "v4l2_format": "mjpeg",         # Use MJPEG for webcams (better performance and compatibility)
            "video_bitrate": "1200k",       # Slightly higher bitrate for clarity
            "video_quality": "medium",      # Keep this or remove if irrelevant to your encoder
            "loglevel": "error",            # Only show errors, suppress info/warning logs
            "hide_banner": "1",             # Hide FFmpeg banner and version info
            "stats_period": "0"             # Disable periodic stats output
        }

        # Add audio options only if enabled
        if enable_audio:
            if sys.platform == 'darwin':
                options.update({
                    "audio": "default",
                    "video": "default"
                })
            else:
                options.update({
                    "audio": "hw:0,0",  # Use first ALSA device
                    "audio_format": "s16le",  # 16-bit PCM
                    "audio_rate": "44100",    # 44.1kHz sample rate
                    "audio_channels": "2"     # Stereo
                })

        logger.info(f"VIDEO STREAM options: {options}")
        
        if sys.platform == 'darwin':
            # On macOS, use avfoundation
            webcam = MediaPlayer("default:none", format="avfoundation", options=options)
        else:
            # On Linux, use v4l2
            webcam = MediaPlayer("/dev/video0", format="v4l2", options=options)

        return (webcam.audio if enable_audio else None), webcam.video  # Return audio only if enabled

def force_codec(pc, sender, forced_codec="video/H264"):
    kind = forced_codec.split("/")[0]
    codecs = RTCRtpSender.getCapabilities(kind).codecs
    transceiver = next(t for t in pc.getTransceivers() if t.sender == sender)
    transceiver.setCodecPreferences(
        [codec for codec in codecs if codec.mimeType == forced_codec]
    )
