import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.orm import AuthToken, Base, User
from services import auth_service


@pytest.fixture
def db_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


async def _create_user(db_factory, password: str = "correct-horse-battery"):
    with db_factory() as session:
        user = User(
            email="robin@example.com",
            username="robin",
            hashed_password=await auth_service.hash_password(password),
            is_verified=True,
        )
        session.add(user)
        session.commit()
        return user.id


@pytest.mark.asyncio
async def test_delete_account_rejects_incorrect_password(db_factory):
    user_id = await _create_user(db_factory)

    success, error = await auth_service.delete_user_account(
        db_factory, user_id, "wrong-password"
    )

    assert success is False
    assert error == "Current password is incorrect"
    with db_factory() as session:
        assert session.get(User, user_id) is not None


@pytest.mark.asyncio
async def test_delete_account_removes_user_and_auth_tokens(db_factory):
    user_id = await _create_user(db_factory)
    with db_factory() as session:
        session.add(
            AuthToken(
                user_id=user_id,
                token="verification-token",
                token_type="email_verification",
                expires_at=auth_service.datetime.now(auth_service.timezone.utc)
                + auth_service.timedelta(hours=1),
            )
        )
        session.commit()

    success, error = await auth_service.delete_user_account(
        db_factory, user_id, "correct-horse-battery"
    )

    assert success is True
    assert error == ""
    with db_factory() as session:
        assert session.get(User, user_id) is None
        assert session.query(AuthToken).count() == 0
