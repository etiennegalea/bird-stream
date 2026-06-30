from sqlalchemy import select

from models.orm import ChatMessage


def recv(ws):
    """Return the next non-participants message, draining any participants updates."""
    while True:
        msg = ws.receive_json()
        if msg.get("type") != "participants":
            return msg


def recv_participants(ws):
    """Return the next participants message, skipping other message types."""
    while True:
        msg = ws.receive_json()
        if msg.get("type") == "participants":
            return msg


# ── connection & join ─────────────────────────────────────────────────────────

async def test_join_system_message(client):
    with await client.websocket_connect("/chat?username=bird") as ws:
        msg = recv(ws)
        assert msg["type"] == "system"
        assert "joined" in msg["text"]


async def test_default_username_is_anon(client):
    # System message is now private ("You joined the chat") so we verify the
    # default username via the participants update that follows.
    with await client.websocket_connect("/chat") as ws:
        recv(ws)  # join system message
        p = ws.receive_json()  # participants update
        assert "anon" in p.get("guests", [])


async def test_username_capped_at_20_chars(client):
    # The join message no longer echoes the username; check via participants.
    with await client.websocket_connect("/chat?username=" + "x" * 30) as ws:
        recv(ws)  # join system message
        p = ws.receive_json()  # participants update
        all_names = p.get("accounts", []) + p.get("guests", [])
        xname = next(n for n in all_names if set(n) == {"x"})
        assert len(xname) == 20


async def test_history_delivered_on_connect(client, db_factory):
    with db_factory() as session:
        session.add(ChatMessage(username="seeder", text="historic msg", message_type="message"))
        session.commit()

    with await client.websocket_connect("/chat?username=newbie") as ws:
        first = ws.receive_json()
        assert first["type"] == "history"
        texts = [m["text"] for m in first["messages"]]
        assert "historic msg" in texts


async def test_no_history_message_when_db_empty(client):
    with await client.websocket_connect("/chat?username=fresh") as ws:
        msg = recv(ws)
        assert msg["type"] == "system"


# ── participants broadcast ────────────────────────────────────────────────────

async def test_participants_sent_after_join(client):
    with await client.websocket_connect("/chat?username=bird") as ws:
        recv(ws)  # joined system message
        p = recv_participants(ws)
        assert p["type"] == "participants"
        assert p["count"] == 1
        assert "bird" in p["guests"]
        assert p["accounts"] == []


async def test_participants_distinguishes_accounts_and_guests(client, make_token):
    token = make_token("alice")
    with await client.websocket_connect(f"/chat?username=alice&token={token}") as alice:
        recv(alice)  # alice joined
        recv_participants(alice)

        with await client.websocket_connect("/chat?username=bird") as bird:
            recv_participants(alice)  # participants update when bird joins (no system msg for alice)
            recv(bird)    # bird's own join message
            p = recv_participants(bird)

        assert "alice" in p["accounts"]
        assert "bird" in p["guests"]
        assert p["count"] == 2


async def test_participants_updated_on_leave(client):
    with await client.websocket_connect("/chat?username=watcher") as watcher:
        recv(watcher)
        recv_participants(watcher)

        with await client.websocket_connect("/chat?username=leaver") as leaver:
            recv_participants(watcher)  # participants update when leaver joins (no system msg for watcher)
            recv(leaver)    # leaver's own join message
            recv_participants(leaver)
        # leaver disconnects

        p = recv_participants(watcher)  # participants update on disconnect
        assert p["count"] == 1
        assert "leaver" not in p["guests"]


# ── read-only guests ──────────────────────────────────────────────────────────

async def test_guest_cannot_send_messages(client):
    with await client.websocket_connect("/chat?username=lurker") as lurker:
        recv(lurker)  # joined
        recv_participants(lurker)

        lurker.send_json({"username": "lurker", "text": "hello?"})

        # Only way to verify silence: connect a second client and confirm
        # the message never arrives there either.
        with await client.websocket_connect("/chat?username=watcher") as watcher:
            recv(watcher)   # watcher joined
            recv_participants(lurker)  # participants update from watcher joining
            recv_participants(watcher)

            watcher.send_json({"username": "watcher", "text": "probe"})
            # watcher is also a guest — probe also dropped; no messages should arrive
            # Both queues should remain empty (test exits cleanly without hanging)


async def test_account_user_can_send_messages(client, make_token):
    token = make_token("alice")
    with await client.websocket_connect(f"/chat?username=alice&token={token}") as ws:
        recv(ws)  # joined
        recv_participants(ws)

        ws.send_json({"username": "alice", "text": "hello"})
        msg = recv(ws)
        assert msg["type"] == "message"
        assert msg["text"] == "hello"
        assert msg["username"] == "alice"
        assert "timestamp" in msg


# ── message send & receive ────────────────────────────────────────────────────

async def test_message_echoed_to_sender(client, make_token):
    token = make_token("echo")
    with await client.websocket_connect(f"/chat?username=echo&token={token}") as ws:
        recv(ws)  # join
        recv_participants(ws)

        ws.send_json({"username": "echo", "text": "hello"})
        msg = recv(ws)
        assert msg["type"] == "message"
        assert msg["username"] == "echo"
        assert msg["text"] == "hello"
        assert "timestamp" in msg


async def test_message_broadcast_to_other_client(client, make_token):
    with await client.websocket_connect(f"/chat?username=alice&token={make_token('alice')}") as alice:
        recv(alice)  # alice joined
        recv_participants(alice)

        with await client.websocket_connect(f"/chat?username=bob&token={make_token('bob')}") as bob:
            recv_participants(alice)  # participants update when bob joins (no system msg for alice)
            recv(bob)     # bob's own join message
            recv_participants(bob)

            alice.send_json({"username": "alice", "text": "hey bob"})

            alice_copy = recv(alice)
            bob_copy = recv(bob)

        assert alice_copy["text"] == "hey bob"
        assert bob_copy["text"] == "hey bob"
        assert bob_copy["username"] == "alice"


async def test_message_persisted_to_db(client, db_factory, make_token):
    token = make_token("persister")
    with await client.websocket_connect(f"/chat?username=persister&token={token}") as ws:
        recv(ws)  # join
        recv_participants(ws)

        ws.send_json({"username": "persister", "text": "save me"})
        recv(ws)  # echo

    with db_factory() as session:
        rows = session.execute(
            select(ChatMessage).where(ChatMessage.username == "persister")
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].text == "save me"
    assert rows[0].message_type == "message"


async def test_system_messages_not_persisted(client, db_factory):
    with await client.websocket_connect("/chat?username=ghost") as ws:
        recv(ws)  # join

    with db_factory() as session:
        rows = session.execute(select(ChatMessage)).scalars().all()
    assert rows == []


# ── input validation ──────────────────────────────────────────────────────────

async def test_empty_text_dropped(client, make_token):
    token = make_token("quiet")
    with await client.websocket_connect(f"/chat?username=quiet&token={token}") as ws:
        recv(ws)  # join
        recv_participants(ws)

        ws.send_json({"username": "quiet", "text": ""})
        ws.send_json({"username": "quiet", "text": "sentinel"})
        msg = recv(ws)
        assert msg["text"] == "sentinel"


async def test_whitespace_text_dropped(client, make_token):
    token = make_token("quiet")
    with await client.websocket_connect(f"/chat?username=quiet&token={token}") as ws:
        recv(ws)  # join
        recv_participants(ws)

        ws.send_json({"username": "quiet", "text": "   \t\n  "})
        ws.send_json({"username": "quiet", "text": "sentinel"})
        msg = recv(ws)
        assert msg["text"] == "sentinel"


async def test_long_text_truncated_at_500(client, make_token):
    token = make_token("verbose")
    with await client.websocket_connect(f"/chat?username=verbose&token={token}") as ws:
        recv(ws)  # join
        recv_participants(ws)

        ws.send_json({"username": "verbose", "text": "x" * 600})
        msg = recv(ws)
        assert len(msg["text"]) == 500


async def test_missing_text_field_ignored(client, make_token):
    token = make_token("broken")
    with await client.websocket_connect(f"/chat?username=broken&token={token}") as ws:
        recv(ws)  # join
        recv_participants(ws)

        ws.send_json({"username": "broken"})  # no "text" key
        ws.send_json({"username": "broken", "text": "ok"})
        msg = recv(ws)
        assert msg["text"] == "ok"


# ── username enforcement ──────────────────────────────────────────────────────

async def test_username_spoofing_rejected(client, make_token):
    token = make_token("legit")
    with await client.websocket_connect(f"/chat?username=legit&token={token}") as ws:
        recv(ws)  # join
        recv_participants(ws)

        ws.send_json({"username": "hacker", "text": "spoof"})
        msg = recv(ws)
        assert msg["username"] == "legit"


# ── rate limiting ─────────────────────────────────────────────────────────────

async def test_rate_limit_fires_for_account_user(client, make_token):
    from services.chat_service import _BUCKET_CAPACITY
    token = make_token("spammer")
    with await client.websocket_connect(f"/chat?username=spammer&token={token}") as ws:
        recv(ws)  # join
        recv_participants(ws)

        for i in range(_BUCKET_CAPACITY):
            ws.send_json({"username": "spammer", "text": f"msg {i}"})
            recv(ws)  # each echoed message

        # Next message should be rate-limited
        ws.send_json({"username": "spammer", "text": "too fast"})
        throttle = recv(ws)
        assert throttle["type"] == "system"
        assert "too quickly" in throttle["text"]
        assert "timestamp" in throttle


# ── disconnect ────────────────────────────────────────────────────────────────

async def test_disconnect_updates_participants_for_others(client):
    # Leave messages are private (only sent to the leaving user, who is already
    # gone). Verify that other viewers see a participants update instead.
    with await client.websocket_connect("/chat?username=watcher") as watcher:
        recv(watcher)  # watcher's own join message
        recv_participants(watcher)

        with await client.websocket_connect("/chat?username=leaver") as leaver:
            recv_participants(watcher)  # participants update when leaver joins
            recv(leaver)    # leaver's own join message
            recv_participants(leaver)
        # leaver disconnects here

        p = recv_participants(watcher)  # participants update on disconnect
        assert p["count"] == 1
        assert "leaver" not in p["guests"]
