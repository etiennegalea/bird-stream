from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt

from services import auth_service


def test_login_token_is_rejected_after_server_session_changes(monkeypatch):
    user = SimpleNamespace(id=7, email="birb@example.com", username="Birb")
    token = auth_service.create_jwt(user)

    assert auth_service.decode_jwt(token)["sub"] == "7"

    monkeypatch.setattr(auth_service, "_SERVER_SESSION_ID", "new-server-process")
    assert auth_service.decode_jwt(token) is None


def test_expired_token_is_rejected():
    token = jwt.encode(
        {
            "sub": "7",
            "server_session": auth_service._SERVER_SESSION_ID,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        auth_service._JWT_SECRET,
        algorithm=auth_service._JWT_ALGORITHM,
    )

    assert auth_service.decode_jwt(token) is None
