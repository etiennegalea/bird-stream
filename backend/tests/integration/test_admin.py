"""Integration tests for admin endpoints and IP blocking."""
import pytest

from controllers.chat_controller import chat_service


# ── helpers (mirrored from test_chat.py) ──────────────────────────────────────

def recv(ws):
    """Return the next non-participants message."""
    while True:
        msg = ws.receive_json()
        if msg.get("type") != "participants":
            return msg


def recv_participants(ws):
    """Return the next participants message."""
    while True:
        msg = ws.receive_json()
        if msg.get("type") == "participants":
            return msg


# ── auth guards ───────────────────────────────────────────────────────────────

async def test_get_users_requires_token(client):
    resp = await client.get("/admin/users")
    assert resp.status_code == 401


async def test_get_users_forbidden_for_non_admin(client, make_token):
    token = make_token("regular")
    resp = await client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_block_ip_requires_token(client):
    resp = await client.post("/admin/block-ip", json={"ip": "1.2.3.4"})
    assert resp.status_code == 401


async def test_block_ip_forbidden_for_non_admin(client, make_token):
    token = make_token("regular")
    resp = await client.post(
        "/admin/block-ip",
        json={"ip": "1.2.3.4"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_unblock_ip_forbidden_for_non_admin(client, make_token):
    token = make_token("regular")
    resp = await client.post(
        "/admin/unblock-ip",
        json={"ip": "1.2.3.4"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── GET /admin/users ──────────────────────────────────────────────────────────

async def test_get_users_shows_empty_state(client, make_admin_token):
    token = make_admin_token()
    resp = await client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accounts"] == []
    assert data["guests"] == []
    assert data["blocked_ips"] == []


async def test_get_users_lists_connected_guest(client, make_admin_token):
    admin_tok = make_admin_token()

    with await client.websocket_connect("/chat?username=birb") as ws:
        recv(ws)
        recv_participants(ws)

        resp = await client.get("/admin/users", headers={"Authorization": f"Bearer {admin_tok}"})
        assert resp.status_code == 200
        data = resp.json()
        guests = [g["username"] for g in data["guests"]]
        assert "birb" in guests
        assert data["accounts"] == []


async def test_get_users_separates_accounts_from_guests(client, make_token, make_admin_token):
    account_tok = make_token("alice")
    admin_tok = make_admin_token()

    with await client.websocket_connect(f"/chat?username=alice&token={account_tok}") as alice:
        recv(alice)
        recv_participants(alice)

        with await client.websocket_connect("/chat?username=birb") as guest:
            recv_participants(alice)
            recv(guest)
            recv_participants(guest)

            resp = await client.get("/admin/users", headers={"Authorization": f"Bearer {admin_tok}"})
            data = resp.json()

        account_names = [a["username"] for a in data["accounts"]]
        guest_names = [g["username"] for g in data["guests"]]
        assert "alice" in account_names
        assert "birb" in guest_names
        assert "birb" not in account_names
        assert "alice" not in guest_names


async def test_get_users_includes_email_for_accounts(client, make_token, make_admin_token):
    account_tok = make_token("alice")
    admin_tok = make_admin_token()

    with await client.websocket_connect(f"/chat?username=alice&token={account_tok}") as ws:
        recv(ws)
        recv_participants(ws)

        resp = await client.get("/admin/users", headers={"Authorization": f"Bearer {admin_tok}"})
        data = resp.json()

    alice = next(a for a in data["accounts"] if a["username"] == "alice")
    assert alice["email"] == "alice@test.example"


# ── POST /admin/block-ip ──────────────────────────────────────────────────────

async def test_block_ip_adds_to_blocked_list(client, make_admin_token):
    admin_tok = make_admin_token()

    resp = await client.post(
        "/admin/block-ip",
        json={"ip": "10.0.0.1"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert resp.status_code == 201
    assert resp.json()["blocked"] == "10.0.0.1"
    assert "10.0.0.1" in chat_service.blocked_ips


async def test_block_ip_appears_in_get_users_response(client, make_admin_token):
    admin_tok = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_tok}"}

    await client.post("/admin/block-ip", json={"ip": "10.0.0.99"}, headers=headers)

    resp = await client.get("/admin/users", headers=headers)
    assert "10.0.0.99" in resp.json()["blocked_ips"]


async def test_block_ip_disconnects_matching_chat_connection(client, make_token, make_admin_token):
    """Blocking an IP closes any active chat connections from that address."""
    victim_ip = "10.20.30.40"
    account_tok = make_token("victim")
    admin_tok = make_admin_token()

    with await client.websocket_connect(
        f"/chat?username=victim&token={account_tok}",
        headers={"x-forwarded-for": victim_ip},
    ) as ws:
        recv(ws)
        recv_participants(ws)

        assert "victim" in chat_service.active_usernames()

        resp = await client.post(
            "/admin/block-ip",
            json={"ip": victim_ip},
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        assert resp.json()["connections_closed"] == 1

    # After the context exits (connection closed by server), user is gone.
    assert "victim" not in chat_service.active_usernames()


async def test_blocking_ip_with_no_active_connection_returns_zero(client, make_admin_token):
    admin_tok = make_admin_token()
    resp = await client.post(
        "/admin/block-ip",
        json={"ip": "192.168.99.99"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert resp.status_code == 201
    assert resp.json()["connections_closed"] == 0


# ── blocked IP chat enforcement ───────────────────────────────────────────────

async def test_blocked_ip_cannot_connect_to_chat(client, make_admin_token):
    """A connection from a blocked IP should be rejected (close code 4403)."""
    blocked_ip = "10.0.1.2"
    chat_service.blocked_ips.add(blocked_ip)

    with pytest.raises(Exception):
        with await client.websocket_connect(
            "/chat?username=blocked",
            headers={"x-forwarded-for": blocked_ip},
        ) as ws:
            ws.receive_json()  # server closes before accept; this should raise

    assert "blocked" not in chat_service.active_usernames()


async def test_non_blocked_ip_can_still_connect(client, make_admin_token):
    """Only the blocked IP is affected; other IPs connect normally."""
    chat_service.blocked_ips.add("10.0.1.2")

    with await client.websocket_connect(
        "/chat?username=legit",
        headers={"x-forwarded-for": "10.0.1.3"},
    ) as ws:
        msg = recv(ws)
        assert msg["type"] == "system"


# ── POST /admin/unblock-ip ────────────────────────────────────────────────────

async def test_unblock_ip_removes_from_blocked_list(client, make_admin_token):
    admin_tok = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_tok}"}

    await client.post("/admin/block-ip", json={"ip": "10.0.0.5"}, headers=headers)
    assert "10.0.0.5" in chat_service.blocked_ips

    resp = await client.post("/admin/unblock-ip", json={"ip": "10.0.0.5"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["unblocked"] == "10.0.0.5"
    assert "10.0.0.5" not in chat_service.blocked_ips


async def test_unblock_ip_no_longer_shown_in_get_users(client, make_admin_token):
    admin_tok = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_tok}"}

    await client.post("/admin/block-ip", json={"ip": "10.0.0.7"}, headers=headers)
    await client.post("/admin/unblock-ip", json={"ip": "10.0.0.7"}, headers=headers)

    resp = await client.get("/admin/users", headers=headers)
    assert "10.0.0.7" not in resp.json()["blocked_ips"]


async def test_unblocked_ip_can_connect_to_chat(client, make_admin_token):
    """After unblocking, that IP can connect to chat again."""
    freed_ip = "10.0.2.5"
    admin_tok = make_admin_token()
    headers = {"Authorization": f"Bearer {admin_tok}"}

    await client.post("/admin/block-ip", json={"ip": freed_ip}, headers=headers)
    await client.post("/admin/unblock-ip", json={"ip": freed_ip}, headers=headers)

    with await client.websocket_connect(
        "/chat?username=freed",
        headers={"x-forwarded-for": freed_ip},
    ) as ws:
        msg = recv(ws)
        assert msg["type"] == "system"
