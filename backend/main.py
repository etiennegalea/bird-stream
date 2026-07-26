import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from aiortc.rtcrtpsender import RTCRtpSender
from dotenv import load_dotenv
from litestar import Litestar
from litestar.config.cors import CORSConfig

_backend_dir = Path(__file__).resolve().parent
load_dotenv(_backend_dir / ".env")                  # local overrides (DB URLs, etc.)
load_dotenv(_backend_dir.parent / ".env")           # root .env (shared secrets)

from controllers.admin_controller import AdminController
from controllers.auth_controller import AuthController
from controllers.chat_controller import chat_endpoint, chat_usernames
from controllers.detection_controller import DetectionController
from controllers.health_controller import health_check
from controllers.mediamtx_controller import MediaMTXController
from controllers.peer_count_controller import peer_count_endpoint
from controllers.queue_controller import queue_endpoint
from controllers.stream_settings_controller import (
    get_stream_catalog,
    get_stream_settings,
    stream_settings_endpoint,
)
from controllers.weather_controller import weather_endpoint
from controllers.webrtc_controller import WebRTCController
from db.session import SessionLocal
from services.auth_service import seed_admin_user
from services.detection_service import DetectionService, detection_enabled
from services.mqtt_service import mqtt_devices
from services.queue_service import QueueService
from services.stream_settings_service import stream_settings
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
    app.state.queue_service = QueueService(pcs_manager)
    stream_settings.load(SessionLocal)

    # Legacy aiortc delivery path. Viewers now use WHEP/HLS served by
    # MediaMTX; keep this off unless reviving the old player.
    if os.environ.get("AIORTC_ENABLED", "false").lower() == "true":
        audio, video = create_local_tracks(enable_audio=True)
        app.state.audio = audio
        app.state.video = video
    else:
        app.state.audio = None
        app.state.video = None
        logger.info("aiortc media path disabled (AIORTC_ENABLED != true)")

    app.state.weather_task = asyncio.create_task(
        fetch_weather_periodically(cache_expiration=3600)
    )

    mqtt_devices.start()  # Pi transmitter status/control bridge

    if detection_enabled():
        app.state.detection_service = DetectionService()
        app.state.detection_service.start()
    else:
        app.state.detection_service = None
        logger.info("Bird detection disabled (set DETECTION_ENABLED=true to enable)")

    await seed_admin_user(
        SessionLocal,
        email=os.environ.get("ADMIN_EMAIL", "admin@birb.local"),
        username=os.environ.get("ADMIN_USERNAME", "admin"),
        password=os.environ.get("ADMIN_PASSWORD", "admin1234"),
    )

    RTCRtpSender.TRANSPORT_POOL_SIZE = 1000
    RTCRtpSender.TRANSPORT_PORT_MIN = 49152
    RTCRtpSender.TRANSPORT_PORT_MAX = 65535

    try:
        yield
    finally:
        mqtt_devices.stop()
        if getattr(app.state, "detection_service", None):
            app.state.detection_service.stop()
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
        AdminController,
        MediaMTXController,
        DetectionController,
        chat_endpoint,
        chat_usernames,
        peer_count_endpoint,
        queue_endpoint,
        get_stream_catalog,
        get_stream_settings,
        stream_settings_endpoint,
    ],
    lifespan=[lifespan],
    cors_config=cors_config,
)
