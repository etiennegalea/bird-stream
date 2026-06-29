import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiortc.rtcrtpsender import RTCRtpSender
from dotenv import load_dotenv
from litestar import Litestar
from litestar.config.cors import CORSConfig

_backend_dir = Path(__file__).resolve().parent
load_dotenv(_backend_dir / ".env")                  # local overrides (DB URLs, etc.)
load_dotenv(_backend_dir.parent / ".env")           # root .env (shared secrets)

from controllers.auth_controller import AuthController
from controllers.chat_controller import chat_endpoint
from controllers.health_controller import health_check
from controllers.peer_count_controller import peer_count_endpoint
from controllers.weather_controller import weather_endpoint
from controllers.webrtc_controller import WebRTCController
from db.session import SessionLocal
from services.video_service import create_local_tracks
from services.weather_service import fetch_weather_periodically
from services.webrtc_service import pcs_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: Litestar):
    logger.info("Application is starting up...")
    app.state.db = SessionLocal
    audio, video = create_local_tracks(enable_audio=False)
    app.state.audio = audio
    app.state.video = video

    app.state.weather_task = asyncio.create_task(
        fetch_weather_periodically(cache_expiration=3600)
    )

    RTCRtpSender.TRANSPORT_POOL_SIZE = 1000
    RTCRtpSender.TRANSPORT_PORT_MIN = 49152
    RTCRtpSender.TRANSPORT_PORT_MAX = 65535

    try:
        yield
    finally:
        await pcs_manager.clean_up()
        logger.info("Application is shutting down...")


cors_config = CORSConfig(
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app = Litestar(
    route_handlers=[
        health_check,
        weather_endpoint,
        WebRTCController,
        AuthController,
        chat_endpoint,
        peer_count_endpoint,
    ],
    lifespan=[lifespan],
    cors_config=cors_config,
)
