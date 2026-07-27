from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.orm import Base, User
from services import email_service


def test_shared_template_escapes_user_supplied_content():
    html = email_service.render_email_template(
        preheader="Preview",
        eyebrow="Welcome",
        title="Hello",
        greeting='Hi <script>alert("oops")</script>,',
        message="A message",
        action_label="Continue",
        action_url='https://example.test/?value="unsafe"&next=yes',
        note="A note",
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&quot;unsafe&quot;&amp;next=yes" in html


def test_app_link_url_encodes_token(monkeypatch):
    monkeypatch.setattr(email_service, "_APP_URL", "https://birds.example")

    assert (
        email_service._app_link(**{"verify-token": "a token&more"})
        == "https://birds.example?verify-token=a+token%26more"
    )


def test_template_uses_public_birb_asset(monkeypatch):
    monkeypatch.setattr(email_service, "_APP_URL", "https://birds.example")

    html = email_service.render_email_template(
        preheader="Preview",
        eyebrow="Welcome",
        title="Hello",
        greeting="Hi Birb,",
        message="A message",
        action_label="Continue",
        action_url="https://birds.example",
        note="A note",
    )

    assert 'src="https://birds.example/birb.png"' in html
    assert "&#127811;" in html


async def test_bird_alert_embeds_and_attaches_snapshot(monkeypatch):
    sent_payload = {}

    async def fake_send(**kwargs):
        sent_payload.update(kwargs)
        return True

    monkeypatch.setattr(email_service, "_send", fake_send)

    assert await email_service.send_bird_alert_email(
        "robin@example.com",
        "Robin",
        b"\xff\xd8sample-jpeg\xff\xd9",
        "27 July 2026 at 21:00",
    )

    assert "Birb is here!" in sent_payload["html"]
    assert "data:image/jpeg;base64," in sent_payload["html"]
    assert sent_payload["attachments"][0]["name"] == "bird-sighting.jpg"
    assert "turn off birb alerts" in sent_payload["text"]


async def test_bird_alerts_only_send_to_eligible_opted_in_users(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db_factory = sessionmaker(bind=engine)
    with db_factory() as session:
        session.add_all([
            User(
                email="opted-in@example.com",
                username="opted-in",
                hashed_password="unused",
                is_verified=True,
                bird_notification_email=True,
            ),
            User(
                email="opted-out@example.com",
                username="opted-out",
                hashed_password="unused",
                is_verified=True,
                bird_notification_email=False,
            ),
            User(
                email="blocked@example.com",
                username="blocked",
                hashed_password="unused",
                is_verified=True,
                is_blocked=True,
                bird_notification_email=True,
            ),
        ])
        session.commit()

    recipients = []

    async def fake_alert(to_email, username, snapshot_jpeg, detected_at):
        recipients.append((to_email, username, snapshot_jpeg, detected_at))
        return True

    monkeypatch.setattr(email_service, "send_bird_alert_email", fake_alert)

    sent = await email_service.send_bird_alerts(
        db_factory, b"jpeg", "27 July 2026 at 21:00"
    )

    assert sent == 1
    assert recipients == [
        ("opted-in@example.com", "opted-in", b"jpeg", "27 July 2026 at 21:00")
    ]
    engine.dispose()
