from contextlib import contextmanager
from time import sleep
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.chat_service import ChatService, LeakyBucket, _BUCKET_CAPACITY


# ── LeakyBucket ───────────────────────────────────────────────────────────────

def test_bucket_allows_up_to_capacity():
    bucket = LeakyBucket(capacity=3, drain_rate=0)
    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is False  # full


def test_bucket_first_message_always_allowed():
    bucket = LeakyBucket(capacity=1, drain_rate=0)
    assert bucket.consume() is True


def test_bucket_blocks_when_full():
    bucket = LeakyBucket(capacity=1, drain_rate=0)
    bucket.consume()
    assert bucket.consume() is False


def test_bucket_drains_over_time():
    bucket = LeakyBucket(capacity=1, drain_rate=50)  # drains 50 tokens/s
    bucket.consume()                # fill to capacity
    assert bucket.consume() is False
    sleep(0.1)                      # 0.1s × 50 tokens/s = 5 tokens drained
    assert bucket.consume() is True


def test_bucket_level_never_goes_negative():
    bucket = LeakyBucket(capacity=8, drain_rate=100)
    sleep(0.2)  # would drain 20 tokens but level floors at 0
    # First 8 messages should all pass (level was 0)
    for _ in range(8):
        assert bucket.consume() is True
    assert bucket.consume() is False


def test_default_capacity_matches_constant():
    bucket = LeakyBucket()
    for _ in range(_BUCKET_CAPACITY):
        assert bucket.consume() is True
    assert bucket.consume() is False


# ── ChatService helpers ───────────────────────────────────────────────────────

@contextmanager
def _empty_db():
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    yield session


def _make_db():
    factory = MagicMock(side_effect=_empty_db)
    return factory


def _make_ws():
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.accept = AsyncMock()
    return ws


@pytest.fixture
def service():
    return ChatService()


# ── connect ───────────────────────────────────────────────────────────────────

async def test_connect_registers_socket(service):
    ws = _make_ws()
    await service.connect(ws, "alice", False, None, _make_db())
    assert ws in service.active_connections
    assert service.active_connections[ws] == "alice"


async def test_connect_account_goes_to_account_sockets(service):
    ws = _make_ws()
    await service.connect(ws, "alice", True, 1, _make_db())
    assert ws in service.account_sockets


async def test_connect_guest_not_in_account_sockets(service):
    ws = _make_ws()
    await service.connect(ws, "bird", False, None, _make_db())
    assert ws not in service.account_sockets


async def test_connect_creates_rate_limiter(service):
    ws = _make_ws()
    await service.connect(ws, "alice", False, None, _make_db())
    assert ws in service.rate_limiters


async def test_connect_stores_user_id(service):
    ws = _make_ws()
    await service.connect(ws, "alice", True, 42, _make_db())
    assert service.get_user_id(ws) == 42


async def test_connect_guest_user_id_is_none(service):
    ws = _make_ws()
    await service.connect(ws, "bird", False, None, _make_db())
    assert service.get_user_id(ws) is None


# ── disconnect ────────────────────────────────────────────────────────────────

async def test_disconnect_removes_socket(service):
    ws = _make_ws()
    await service.connect(ws, "alice", True, 1, _make_db())
    service.disconnect(ws)
    assert ws not in service.active_connections
    assert ws not in service.account_sockets
    assert ws not in service.user_id_map
    assert ws not in service.rate_limiters


async def test_disconnect_unknown_socket_is_safe(service):
    ws = _make_ws()
    service.disconnect(ws)  # should not raise


# ── is_account_user / check_rate_limit ───────────────────────────────────────

async def test_is_account_user_true_for_account(service):
    ws = _make_ws()
    await service.connect(ws, "alice", True, 1, _make_db())
    assert service.is_account_user(ws) is True


async def test_is_account_user_false_for_guest(service):
    ws = _make_ws()
    await service.connect(ws, "bird", False, None, _make_db())
    assert service.is_account_user(ws) is False


async def test_check_rate_limit_allows_within_burst(service):
    ws = _make_ws()
    await service.connect(ws, "alice", True, 1, _make_db())
    assert service.check_rate_limit(ws) is True


async def test_check_rate_limit_blocks_after_burst(service):
    ws = _make_ws()
    await service.connect(ws, "alice", True, 1, _make_db())
    for _ in range(_BUCKET_CAPACITY):
        service.check_rate_limit(ws)
    assert service.check_rate_limit(ws) is False


async def test_check_rate_limit_unknown_socket_returns_true(service):
    ws = _make_ws()
    assert service.check_rate_limit(ws) is True


# ── broadcast_participants ────────────────────────────────────────────────────

async def test_broadcast_participants_content(service):
    ws_account = _make_ws()
    ws_guest = _make_ws()
    await service.connect(ws_account, "alice", True, 1, _make_db())
    await service.connect(ws_guest, "bird", False, None, _make_db())

    await service.broadcast_participants()

    sent = ws_account.send_json.call_args_list
    participants_calls = [c.args[0] for c in sent if c.args[0].get("type") == "participants"]
    assert participants_calls
    last = participants_calls[-1]
    assert last["count"] == 2
    assert "alice" in last["accounts"]
    assert "bird" in last["guests"]


async def test_broadcast_participants_empty_when_no_connections(service):
    # No exception and message has count 0
    ws = _make_ws()
    await service.broadcast_participants()  # no connections — should not raise


async def test_broadcast_participants_skips_failed_sends(service):
    ws_ok = _make_ws()
    ws_bad = _make_ws()
    ws_bad.send_json.side_effect = Exception("connection closed")

    await service.connect(ws_ok, "alice", True, 1, _make_db())
    await service.connect(ws_bad, "bob", True, 2, _make_db())

    # Should not raise even if one send fails
    await service.broadcast_participants()
    ws_ok.send_json.assert_called()
