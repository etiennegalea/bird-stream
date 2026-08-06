from contextlib import asynccontextmanager

from litestar import Litestar
from litestar.testing import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from controllers.auth_controller import AuthController
from models.orm import Base, User
from services.auth_service import create_jwt
from services.profanity_service import record_profanities


def _app_and_users():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db_factory = sessionmaker(bind=engine)
    with db_factory() as session:
        writer = User(
            email="writer@example.com",
            username="writer",
            hashed_password="unused",
            is_verified=True,
            profanity_filter_enabled=True,
        )
        viewer = User(
            email="viewer@example.com",
            username="viewer",
            hashed_password="unused",
            is_verified=True,
            profanity_filter_enabled=False,
        )
        filtered_viewer = User(
            email="filtered@example.com",
            username="filtered",
            hashed_password="unused",
            is_verified=True,
            profanity_filter_enabled=True,
        )
        session.add_all([writer, viewer, filtered_viewer])
        session.flush()
        writer_id = writer.id
        viewer_token = create_jwt(viewer)
        filtered_token = create_jwt(filtered_viewer)
        record_profanities(session, writer_id, "fuck fuck żobbi")
        session.commit()

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = db_factory
        yield

    app = Litestar(route_handlers=[AuthController], lifespan=[lifespan])
    return engine, db_factory, app, writer_id, viewer_token, filtered_token


def test_filter_off_viewer_sees_another_users_counts_regardless_of_target_setting():
    engine, _, app, writer_id, viewer_token, _ = _app_and_users()
    with TestClient(app=app) as client:
        response = client.get(
            f"/auth/profile/public/id/{writer_id}",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )

    assert response.status_code == 200
    assert response.json()["can_view_profanities"] is True
    assert response.json()["profanities"] == [
        {"word": "fuck", "count": 2},
        {"word": "żobb", "count": 1},
    ]
    engine.dispose()


def test_writer_sees_own_counts_after_turning_their_filter_off():
    engine, db_factory, app, writer_id, _, _ = _app_and_users()
    with db_factory() as session:
        writer = session.get(User, writer_id)
        writer.profanity_filter_enabled = False
        writer_token = create_jwt(writer)
        session.commit()

    with TestClient(app=app) as client:
        response = client.get(
            f"/auth/profile/public/id/{writer_id}",
            headers={"Authorization": f"Bearer {writer_token}"},
        )

    assert response.status_code == 200
    assert response.json()["can_view_profanities"] is True
    assert response.json()["profanities"][0] == {"word": "fuck", "count": 2}
    engine.dispose()


def test_filter_on_viewer_cannot_receive_counts():
    engine, _, app, writer_id, _, filtered_token = _app_and_users()
    with TestClient(app=app) as client:
        response = client.get(
            f"/auth/profile/public/id/{writer_id}",
            headers={"Authorization": f"Bearer {filtered_token}"},
        )

    assert response.status_code == 200
    assert response.json()["can_view_profanities"] is False
    assert "profanities" not in response.json()
    engine.dispose()
