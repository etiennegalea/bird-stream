from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.orm import Base, ChatMessage, ProfanityOccurrence, User
from services.profanity_service import extract_profanities, get_profanity_counts, record_profanities
from services.auth_service import get_public_profile_by_id


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        user = User(email="finch@example.com", username="finch", hashed_password="unused")
        session.add(user)
        session.commit()
        return engine, factory, user.id


def test_detects_english_and_maltese_whole_words():
    counts = extract_profanities("Fuck fuck, qaħba qahba and classic.")
    assert counts == {"fuck": 2, "qaħba": 2}


def test_detects_racial_slur_variants_as_complete_words():
    counts = extract_profanities("nigga NIGGER niggas")
    assert counts == {"nigga": 2, "nigger": 1}


def test_detects_expanded_english_profanity_and_obfuscations():
    counts = extract_profanities("damn douchebag prick f*ck a$$hole")
    assert counts == {
        "damn": 1,
        "douchebag": 1,
        "prick": 1,
        "fuck": 1,
        "asshole": 1,
    }


def test_detects_maltese_inflections_and_keyboard_spellings():
    counts = extract_profanities("żobbi zobbhom sormok mnieghel pacocc")
    assert counts == {
        "żobb": 2,
        "sorm": 1,
        "mniegħel": 1,
        "paċoċċ": 1,
    }


def test_does_not_treat_a_bird_name_as_profanity():
    assert extract_profanities("A blue tit visited today") == {}


def test_records_every_occurrence_and_returns_rolling_counts():
    engine, factory, user_id = _db()
    now = datetime.now(timezone.utc)
    with factory() as session:
        record_profanities(session, user_id, "shit shit foxx", now)
        session.commit()

    with factory() as session:
        assert get_profanity_counts(session, user_id, now) == [
            {"word": "shit", "count": 2},
            {"word": "foxx", "count": 1},
        ]
    engine.dispose()


def test_expired_occurrences_are_removed(monkeypatch):
    monkeypatch.setenv("PROFANITY_RETENTION_DAYS", "7")
    engine, factory, user_id = _db()
    now = datetime.now(timezone.utc)
    with factory() as session:
        record_profanities(session, user_id, "fuck", now - timedelta(days=8))
        session.commit()

    with factory() as session:
        assert get_profanity_counts(session, user_id, now) == []
        assert session.query(ProfanityOccurrence).count() == 0
    engine.dispose()


def test_public_profile_only_includes_counts_when_requested():
    engine, factory, user_id = _db()
    with factory() as session:
        record_profanities(session, user_id, "foxx")
        session.add_all([
            ChatMessage(
                user_id=user_id, username="finch", text="hidden",
                is_deleted=True,
            ),
            ChatMessage(
                user_id=user_id, username="finch", text="visible",
                is_deleted=False,
            ),
        ])
        session.commit()

    hidden = get_public_profile_by_id(factory, user_id)
    visible = get_public_profile_by_id(factory, user_id, include_profanities=True)

    assert "profanities" not in hidden
    assert visible["profanities"] == [{"word": "foxx", "count": 1}]
    assert visible["profanity_retention_days"] == 7
    assert visible["deleted_message_count"] == 1
    engine.dispose()
