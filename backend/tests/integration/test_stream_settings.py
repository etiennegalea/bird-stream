"""Integration tests for admin stream controls and private viewer access."""

import services.auth_service as auth_svc
from models.orm import StreamConfiguration
from services.mqtt_service import mqtt_devices
from services.stream_settings_service import stream_settings


# ── auth guards (admin endpoints) ─────────────────────────────────────────────

async def test_get_stream_settings_requires_token(client):
    resp = await client.get("/admin/stream-settings")
    assert resp.status_code == 401


async def test_get_stream_settings_forbidden_for_non_admin(client, make_token):
    token = make_token("regular")
    resp = await client.get(
        "/admin/stream-settings", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_update_stream_settings_requires_token(client):
    resp = await client.post("/admin/stream-settings", json={"video_enabled": False})
    assert resp.status_code == 401


async def test_update_stream_settings_forbidden_for_non_admin(client, make_token):
    token = make_token("regular")
    resp = await client.post(
        "/admin/stream-settings",
        json={"video_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert stream_settings.video_enabled is True  # unchanged


# ── admin toggling ────────────────────────────────────────────────────────────

async def test_defaults_video_on_audio_off(client, make_admin_token):
    """Audio must never be on by default — enabling it is a deliberate act."""
    token = make_admin_token()
    resp = await client.get(
        "/admin/stream-settings", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "video_enabled": True,
        "audio_enabled": False,
        "private_enabled": False,
    }


async def test_admin_can_disable_video(client, make_admin_token):
    token = make_admin_token()
    resp = await client.post(
        "/admin/stream-settings",
        json={"video_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json() == {
        "video_enabled": False,
        "audio_enabled": False,
        "private_enabled": False,
    }
    assert stream_settings.video_enabled is False


async def test_admin_can_enable_audio(client, make_admin_token):
    token = make_admin_token()
    resp = await client.post(
        "/admin/stream-settings",
        json={"audio_enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json() == {
        "video_enabled": True,
        "audio_enabled": True,
        "private_enabled": False,
    }
    assert stream_settings.audio_enabled is True


async def test_partial_update_leaves_other_setting_untouched(client, make_admin_token):
    token = make_admin_token()
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/admin/stream-settings", json={"audio_enabled": True}, headers=headers)
    resp = await client.post("/admin/stream-settings", json={"video_enabled": False}, headers=headers)
    assert resp.json() == {
        "video_enabled": False,
        "audio_enabled": True,
        "private_enabled": False,
    }

    resp = await client.post("/admin/stream-settings", json={"audio_enabled": False}, headers=headers)
    assert resp.json() == {
        "video_enabled": False,
        "audio_enabled": False,
        "private_enabled": False,
    }


async def test_empty_update_rejected(client, make_admin_token):
    token = make_admin_token()
    resp = await client.post(
        "/admin/stream-settings", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 400


# ── public read access ────────────────────────────────────────────────────────

async def test_public_settings_endpoint_needs_no_auth(client):
    resp = await client.get("/stream/settings")
    assert resp.status_code == 200
    assert resp.json() == {
        "video_enabled": True,
        "audio_enabled": False,
        "private_enabled": False,
    }


async def test_public_settings_reflect_admin_changes(client, make_admin_token):
    token = make_admin_token()
    await client.post(
        "/admin/stream-settings",
        json={"video_enabled": False, "audio_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get("/stream/settings")
    assert resp.json() == {
        "video_enabled": False,
        "audio_enabled": False,
        "private_enabled": False,
    }


async def test_stream_settings_ws_pushes_initial_state(client, make_admin_token):
    token = make_admin_token()
    await client.post(
        "/admin/stream-settings",
        json={"audio_enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    with await client.websocket_connect("/stream-settings") as ws:
        msg = ws.receive_json()
        assert msg == {
            "video_enabled": True,
            "audio_enabled": True,
            "private_enabled": False,
        }


async def test_stream_settings_ws_pushes_updates(client, make_admin_token):
    token = make_admin_token()

    with await client.websocket_connect("/stream-settings") as ws:
        assert ws.receive_json() == {
            "video_enabled": True,
            "audio_enabled": False,
            "private_enabled": False,
        }

        await client.post(
            "/admin/stream-settings",
            json={"video_enabled": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert ws.receive_json() == {
            "video_enabled": False,
            "audio_enabled": False,
            "private_enabled": False,
        }


# ── private viewer access ─────────────────────────────────────────────────────

async def test_admin_can_make_stream_private_and_setting_is_persisted(
    client, make_admin_token, db_factory
):
    token = make_admin_token()
    resp = await client.post(
        "/admin/stream-settings",
        json={"private_enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["private_enabled"] is True
    assert stream_settings.private_enabled is True

    stream_settings.reset()
    stream_settings.load(db_factory)
    assert stream_settings.private_enabled is True
    with db_factory() as session:
        assert session.get(StreamConfiguration, 1).private_enabled is True


async def test_private_catalog_is_empty_for_public_viewer(
    client, make_admin_token, monkeypatch
):
    monkeypatch.setattr(
        mqtt_devices,
        "stream_catalog",
        lambda: [{"path": "birdcam", "available": True}],
    )
    token = make_admin_token()
    await client.post(
        "/admin/stream-settings",
        json={"private_enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await client.get("/stream/catalog")
    assert resp.status_code == 200
    assert resp.json() == {"streams": []}


async def test_private_catalog_remains_visible_to_admin(
    client, make_admin_token, monkeypatch
):
    catalog = [{"path": "birdcam", "available": True}]
    monkeypatch.setattr(mqtt_devices, "stream_catalog", lambda: catalog)
    token = make_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/admin/stream-settings",
        json={"private_enabled": True},
        headers=headers,
    )

    resp = await client.get("/stream/catalog", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"streams": catalog}


async def test_stream_access_token_requires_admin(client, make_token):
    token = make_token("regular")
    resp = await client.post(
        "/admin/stream-access-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_admin_receives_narrow_short_lived_stream_token(
    client, make_admin_token
):
    token = make_admin_token()
    resp = await client.post(
        "/admin/stream-access-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    payload = auth_svc.decode_stream_access_token(data["token"])
    assert payload is not None
    assert payload["scope"] == "stream:read:admin"
    assert data["expires_in"] > 0
