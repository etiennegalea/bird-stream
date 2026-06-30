"""Unit tests for QueueService queue-management logic.

Tests use a FakePcsManager that mimics ConnectionManager's interface so the
queue service can be exercised without a real WebRTC stack or database.
"""

import pytest

from services.queue_service import QueueService, _READY


# ── helpers ───────────────────────────────────────────────────────────────────

class FakePcsManager:
    """Minimal stand-in for ConnectionManager."""

    def __init__(self, peer_count: int = 0):
        self.pcs: dict[str, object] = {str(i): None for i in range(peer_count)}
        self._listeners = []

    def on_change(self, cb) -> None:
        self._listeners.append(cb)

    def remove_change_listener(self, cb) -> None:
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    def add_peer(self, peer_id: str = "x") -> None:
        self.pcs[peer_id] = None
        for cb in self._listeners[:]:
            cb()

    def remove_peer(self, peer_id: str) -> None:
        self.pcs.pop(peer_id, None)
        for cb in self._listeners[:]:
            cb()


def make_service(max_viewers: int, peer_count: int = 0) -> tuple[QueueService, FakePcsManager]:
    mgr = FakePcsManager(peer_count)
    svc = QueueService.__new__(QueueService)
    svc._pcs = mgr
    svc._waiting = []
    svc._max_viewers = max_viewers
    svc._pending = 0
    svc._last_peer_count = peer_count
    mgr.on_change(svc._on_peer_change)
    return svc, mgr


# ── slot_available ────────────────────────────────────────────────────────────

def test_slot_available_when_below_limit():
    svc, _ = make_service(max_viewers=2, peer_count=1)
    assert svc.slot_available() is True


def test_slot_not_available_when_at_limit():
    svc, _ = make_service(max_viewers=2, peer_count=2)
    assert svc.slot_available() is False


def test_slot_not_available_when_peer_count_plus_pending_reaches_limit():
    svc, _ = make_service(max_viewers=2, peer_count=1)
    svc.reserve()  # pending = 1 → occupied = 2
    assert svc.slot_available() is False


def test_slot_available_after_release():
    svc, _ = make_service(max_viewers=1, peer_count=0)
    svc.reserve()
    assert svc.slot_available() is False
    svc.release()
    assert svc.slot_available() is True


# ── enqueue / position_of ─────────────────────────────────────────────────────

def test_first_enqueued_client_is_at_position_1():
    svc, _ = make_service(max_viewers=1, peer_count=1)
    ch = svc.enqueue()
    assert svc.position_of(ch) == 1


def test_second_enqueued_client_is_at_position_2():
    svc, _ = make_service(max_viewers=1, peer_count=1)
    svc.enqueue()
    ch2 = svc.enqueue()
    assert svc.position_of(ch2) == 2


def test_position_of_unknown_channel_is_zero():
    import asyncio
    svc, _ = make_service(max_viewers=1, peer_count=1)
    orphan = asyncio.Queue()
    assert svc.position_of(orphan) == 0


# ── promotion when a peer leaves ──────────────────────────────────────────────

def test_first_in_queue_receives_ready_when_peer_leaves():
    """The 1st person in queue gets the ready signal when a spot opens."""
    svc, mgr = make_service(max_viewers=1, peer_count=1)
    ch1 = svc.enqueue()

    mgr.remove_peer("0")

    assert ch1.get_nowait() == _READY


def test_second_becomes_first_when_peer_leaves():
    """When a spot opens, ch1 is promoted and ch2 moves to position 1."""
    svc, mgr = make_service(max_viewers=1, peer_count=1)
    ch1 = svc.enqueue()
    ch2 = svc.enqueue()

    mgr.remove_peer("0")

    # ch1 is promoted
    assert ch1.get_nowait() == _READY
    # ch2 is now first in line
    assert svc.position_of(ch2) == 1


def test_second_gets_position_update_pushed_to_channel_when_first_promoted():
    """After promotion, the position update (1) is pushed into ch2's channel."""
    svc, mgr = make_service(max_viewers=1, peer_count=1)
    svc.enqueue()   # ch1
    ch2 = svc.enqueue()

    mgr.remove_peer("0")

    assert ch2.get_nowait() == 1  # pushed as a position update


def test_only_one_client_promoted_per_freed_slot():
    """A single freed slot promotes exactly one waiting client, not all of them."""
    svc, mgr = make_service(max_viewers=1, peer_count=1)
    ch1 = svc.enqueue()
    ch2 = svc.enqueue()
    ch3 = svc.enqueue()

    mgr.remove_peer("0")

    assert ch1.get_nowait() == _READY
    assert svc.position_of(ch2) == 1  # still waiting
    assert svc.position_of(ch3) == 2  # still waiting


# ── dequeue (client leaves the waiting room) ──────────────────────────────────

def test_second_stays_second_when_third_leaves_queue():
    """Removing the 3rd queued client does not affect positions 1 and 2."""
    svc, _ = make_service(max_viewers=1, peer_count=1)
    ch1 = svc.enqueue()
    ch2 = svc.enqueue()
    ch3 = svc.enqueue()

    svc.dequeue(ch3)

    assert svc.position_of(ch1) == 1
    assert svc.position_of(ch2) == 2


def test_third_removed_from_waiting_list_after_dequeue():
    svc, _ = make_service(max_viewers=1, peer_count=1)
    svc.enqueue()
    svc.enqueue()
    ch3 = svc.enqueue()

    svc.dequeue(ch3)

    assert svc.position_of(ch3) == 0


def test_dequeue_of_first_shifts_second_to_position_1():
    svc, _ = make_service(max_viewers=1, peer_count=1)
    ch1 = svc.enqueue()
    ch2 = svc.enqueue()

    svc.dequeue(ch1)

    assert svc.position_of(ch2) == 1


def test_dequeue_pushes_updated_position_into_remaining_channel():
    """After ch1 leaves the queue, ch2's channel receives position 1."""
    svc, _ = make_service(max_viewers=1, peer_count=1)
    ch1 = svc.enqueue()
    ch2 = svc.enqueue()

    # Drain the initial position push that happened on enqueue
    while not ch2.empty():
        ch2.get_nowait()

    svc.dequeue(ch1)

    assert ch2.get_nowait() == 1


def test_dequeue_of_promoted_client_releases_pending_slot():
    """If a promoted client's queue WS closes without connecting, the pending
    reservation is released so the next waiter can be promoted."""
    svc, mgr = make_service(max_viewers=1, peer_count=1)
    ch1 = svc.enqueue()
    ch2 = svc.enqueue()

    mgr.remove_peer("0")       # ch1 promoted, pending = 1
    assert ch1.get_nowait() == _READY

    # ch1 closes its queue WS without connecting
    svc.dequeue(ch1)           # ch1 not in _waiting → release → promote ch2

    assert ch2.get_nowait() == _READY


# ── reserve / release (immediate-ready path) ──────────────────────────────────

def test_reserve_blocks_concurrent_slot():
    """A reserved slot makes slot_available False so a second caller is queued."""
    svc, _ = make_service(max_viewers=1, peer_count=0)
    svc.reserve()
    assert svc.slot_available() is False


def test_release_restores_slot_and_promotes_next_waiter():
    svc, _ = make_service(max_viewers=1, peer_count=0)
    svc.reserve()
    ch = svc.enqueue()

    svc.release()  # slot freed — should promote ch

    assert ch.get_nowait() == _READY


# ── pending resolves when peer connects ───────────────────────────────────────

def test_pending_decrements_when_peer_connects():
    svc, mgr = make_service(max_viewers=2, peer_count=1)
    svc.reserve()              # pending = 1 (slot given to a waiting client)
    assert svc._pending == 1

    mgr.add_peer("new")        # the waiting client connected
    assert svc._pending == 0


def test_two_slots_open_promote_two_clients():
    svc, mgr = make_service(max_viewers=3, peer_count=3)
    ch1 = svc.enqueue()
    ch2 = svc.enqueue()
    ch3 = svc.enqueue()

    mgr.remove_peer("0")  # frees 1 slot → promotes ch1
    mgr.remove_peer("1")  # frees 1 more slot → promotes ch2

    assert ch1.get_nowait() == _READY
    assert ch2.get_nowait() == _READY
    assert svc.position_of(ch3) == 1  # ch3 still waiting at position 1
