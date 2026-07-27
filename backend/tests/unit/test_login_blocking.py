import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.orm import Base, User
from services import auth_service


@pytest.fixture
def db_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


async def create_user(db_factory, *, blocked=False):
    with db_factory() as session:
        user = User(
            email="birb@example.com",
            username="birb",
            hashed_password=await auth_service.hash_password("password1"),
            is_verified=True,
            is_blocked=blocked,
        )
        session.add(user)
        session.commit()


@pytest.mark.asyncio
async def test_successful_login_updates_last_ip(db_factory):
    await create_user(db_factory)
    token, user, error = await auth_service.login_user(
        db_factory, "birb", "password1", client_ip="8.8.8.8")

    assert token
    assert user["username"] == "birb"
    assert error == ""
    with db_factory() as session:
        assert session.query(User).one().last_ip == "8.8.8.8"


@pytest.mark.asyncio
async def test_blocked_user_cannot_login(db_factory):
    await create_user(db_factory, blocked=True)
    token, user, error = await auth_service.login_user(
        db_factory, "birb", "password1", client_ip="8.8.8.8")

    assert token is None
    assert user is None
    assert error == "Account has been blocked"
