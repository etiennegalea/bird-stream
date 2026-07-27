from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.orm import Base, User
from services.auth_service import get_user_profile, update_user_profile


def test_bird_notification_preference_defaults_off_and_can_be_enabled():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db_factory = sessionmaker(bind=engine)
    with db_factory() as session:
        user = User(
            email="robin@example.com",
            username="robin",
            hashed_password="unused",
            is_verified=True,
        )
        session.add(user)
        session.commit()
        user_id = user.id

    assert get_user_profile(db_factory, user_id)["bird_notification_email"] is False

    profile, error = update_user_profile(
        db_factory,
        user_id,
        email=None,
        username=None,
        bio=None,
        avatar=None,
        bird_notification_email=True,
    )

    assert error == ""
    assert profile["bird_notification_email"] is True
    engine.dispose()
