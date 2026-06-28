from sqlalchemy import select

from models.orm import ChatMessage


# ── connection & join ─────────────────────────────────────────────────────────

async def test_join_system_message(client):
    with await client.websocket_connect("/chat?username=bird") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "system"
        assert "bird" in msg["text"]
        assert "joined" in msg["text"]


async def test_default_username_is_anon(client):
    with await client.websocket_connect("/chat") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "system"
        assert "anon" in msg["text"]


async def test_username_capped_at_20_chars(client):
    with await client.websocket_connect("/chat?username=" + "x" * 30) as ws:
        msg = ws.receive_json()
        username_word = next(w for w in msg["text"].split() if set(w) == {"x"})
        assert len(username_word) == 20


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
        msg = ws.receive_json()
        assert msg["type"] == "system"


# ── message send & receive ────────────────────────────────────────────────────

async def test_message_echoed_to_sender(client):
    with await client.websocket_connect("/chat?username=echo") as ws:
        ws.receive_json()  # join
        ws.send_json({"username": "echo", "text": "hello"})
        msg = ws.receive_json()
        assert msg["type"] == "message"
        assert msg["username"] == "echo"
        assert msg["text"] == "hello"
        assert "timestamp" in msg


async def test_message_broadcast_to_other_client(client):
    with await client.websocket_connect("/chat?username=alice") as alice:
        alice.receive_json()  # alice joined

        with await client.websocket_connect("/chat?username=bob") as bob:
            alice.receive_json()  # bob joined (alice sees it)
            bob.receive_json()    # bob joined (bob sees it)

            alice.send_json({"username": "alice", "text": "hey bob"})

            alice_copy = alice.receive_json()
            bob_copy = bob.receive_json()

        assert alice_copy["text"] == "hey bob"
        assert bob_copy["text"] == "hey bob"
        assert bob_copy["username"] == "alice"


async def test_message_persisted_to_db(client, db_factory):
    with await client.websocket_connect("/chat?username=persister") as ws:
        ws.receive_json()  # join
        ws.send_json({"username": "persister", "text": "save me"})
        ws.receive_json()  # echo

    with db_factory() as session:
        rows = session.execute(
            select(ChatMessage).where(ChatMessage.username == "persister")
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].text == "save me"
    assert rows[0].message_type == "message"


async def test_system_messages_not_persisted(client, db_factory):
    with await client.websocket_connect("/chat?username=ghost") as ws:
        ws.receive_json()  # join

    with db_factory() as session:
        rows = session.execute(select(ChatMessage)).scalars().all()
    assert rows == []


# ── input validation ──────────────────────────────────────────────────────────

async def test_empty_text_dropped(client):
    with await client.websocket_connect("/chat?username=quiet") as ws:
        ws.receive_json()  # join
        ws.send_json({"username": "quiet", "text": ""})
        ws.send_json({"username": "quiet", "text": "sentinel"})
        msg = ws.receive_json()
        assert msg["text"] == "sentinel"


async def test_whitespace_text_dropped(client):
    with await client.websocket_connect("/chat?username=quiet") as ws:
        ws.receive_json()  # join
        ws.send_json({"username": "quiet", "text": "   \t\n  "})
        ws.send_json({"username": "quiet", "text": "sentinel"})
        msg = ws.receive_json()
        assert msg["text"] == "sentinel"


async def test_long_text_truncated_at_500(client):
    with await client.websocket_connect("/chat?username=verbose") as ws:
        ws.receive_json()  # join
        ws.send_json({"username": "verbose", "text": "x" * 600})
        msg = ws.receive_json()
        assert len(msg["text"]) == 500


async def test_missing_text_field_ignored(client):
    with await client.websocket_connect("/chat?username=broken") as ws:
        ws.receive_json()  # join
        ws.send_json({"username": "broken"})  # no "text" key
        ws.send_json({"username": "broken", "text": "ok"})
        msg = ws.receive_json()
        assert msg["text"] == "ok"


# ── username enforcement ──────────────────────────────────────────────────────

async def test_username_spoofing_rejected(client):
    with await client.websocket_connect("/chat?username=legit") as ws:
        ws.receive_json()  # join
        ws.send_json({"username": "hacker", "text": "spoof"})
        msg = ws.receive_json()
        assert msg["username"] == "legit"


# ── disconnect ────────────────────────────────────────────────────────────────

async def test_disconnect_broadcasts_leave(client):
    with await client.websocket_connect("/chat?username=watcher") as watcher:
        watcher.receive_json()  # watcher joined

        with await client.websocket_connect("/chat?username=leaver") as leaver:
            watcher.receive_json()  # leaver joined (watcher sees)
            leaver.receive_json()   # leaver joined (leaver sees)
        # leaver disconnects here

        leave_msg = watcher.receive_json()
        assert leave_msg["type"] == "system"
        assert "leaver" in leave_msg["text"]
        assert "left" in leave_msg["text"]
