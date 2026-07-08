"""Integration tests for admin stream toggle controls."""

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

async def test_defaults_are_enabled(client, make_admin_token):
    token = make_admin_token()
    resp = await client.get(
        "/admin/stream-settings", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"video_enabled": True, "audio_enabled": True}


async def test_admin_can_disable_video(client, make_admin_token):
    token = make_admin_token()
    resp = await client.post(
        "/admin/stream-settings",
        json={"video_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json() == {"video_enabled": False, "audio_enabled": True}
    assert stream_settings.video_enabled is False


async def test_admin_can_disable_audio(client, make_admin_token):
    token = make_admin_token()
    resp = await client.post(
        "/admin/stream-settings",
        json={"audio_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json() == {"video_enabled": True, "audio_enabled": False}
    assert stream_settings.audio_enabled is False


async def test_partial_update_leaves_other_setting_untouched(client, make_admin_token):
    token = make_admin_token()
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/admin/stream-settings", json={"video_enabled": False}, headers=headers)
    resp = await client.post("/admin/stream-settings", json={"audio_enabled": False}, headers=headers)
    assert resp.json() == {"video_enabled": False, "audio_enabled": False}

    resp = await client.post("/admin/stream-settings", json={"video_enabled": True}, headers=headers)
    assert resp.json() == {"video_enabled": True, "audio_enabled": False}


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
    assert resp.json() == {"video_enabled": True, "audio_enabled": True}


async def test_public_settings_reflect_admin_changes(client, make_admin_token):
    token = make_admin_token()
    await client.post(
        "/admin/stream-settings",
        json={"video_enabled": False, "audio_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get("/stream/settings")
    assert resp.json() == {"video_enabled": False, "audio_enabled": False}


async def test_stream_settings_ws_pushes_initial_state(client, make_admin_token):
    token = make_admin_token()
    await client.post(
        "/admin/stream-settings",
        json={"audio_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )

    with await client.websocket_connect("/stream-settings") as ws:
        msg = ws.receive_json()
        assert msg == {"video_enabled": True, "audio_enabled": False}


async def test_stream_settings_ws_pushes_updates(client, make_admin_token):
    token = make_admin_token()

    with await client.websocket_connect("/stream-settings") as ws:
        assert ws.receive_json() == {"video_enabled": True, "audio_enabled": True}

        await client.post(
            "/admin/stream-settings",
            json={"video_enabled": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert ws.receive_json() == {"video_enabled": False, "audio_enabled": True}
