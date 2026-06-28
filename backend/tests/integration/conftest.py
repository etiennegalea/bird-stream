import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from aiortc.rtcrtpsender import RTCRtpSender
from dotenv import load_dotenv
from litestar import Litestar
from litestar.config.cors import CORSConfig
from litestar.testing import AsyncTestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import sessionmaker

from controllers.chat_controller import chat_endpoint, chat_service
from controllers.health_controller import health_check
from controllers.peer_count_controller import peer_count_endpoint
from controllers.weather_controller import weather_endpoint
from controllers.webrtc_controller import WebRTCController
from models.orm import Base, ChatMessage

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

_ADMIN_URL = os.environ["ADMIN_DATABASE_URL"]
_TEST_DB_URL = os.environ["TEST_DATABASE_URL"]


@pytest.fixture(scope="session")
def test_engine():
    admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'birb_test_db' AND pid <> pg_backend_pid()"
        ))
        conn.execute(text("DROP DATABASE IF EXISTS birb_test_db"))
        conn.execute(text("CREATE DATABASE birb_test_db"))

    engine = create_engine(_TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS birb_test_db"))
    admin.dispose()


@pytest.fixture(scope="session")
def db_factory(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session")
def litestar_app(db_factory):
    @asynccontextmanager
    async def test_lifespan(app: Litestar):
        app.state.db = db_factory
        app.state.audio = None
        app.state.video = None
        RTCRtpSender.TRANSPORT_POOL_SIZE = 1000
        RTCRtpSender.TRANSPORT_PORT_MIN = 49152
        RTCRtpSender.TRANSPORT_PORT_MAX = 65535
        yield

    return Litestar(
        route_handlers=[
            health_check,
            weather_endpoint,
            WebRTCController,
            chat_endpoint,
            peer_count_endpoint,
        ],
        lifespan=[test_lifespan],
        cors_config=CORSConfig(allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
    )


@pytest_asyncio.fixture
async def client(litestar_app):
    async with AsyncTestClient(app=litestar_app) as c:
        yield c


@pytest.fixture(autouse=True)
def isolate(db_factory):
    """Clear chat connections and wipe test messages around every test."""
    chat_service.active_connections.clear()
    yield
    chat_service.active_connections.clear()
    with db_factory() as session:
        session.execute(delete(ChatMessage))
        session.commit()
