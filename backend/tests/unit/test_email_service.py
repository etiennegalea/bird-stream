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
