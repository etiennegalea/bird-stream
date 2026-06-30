import asyncio
import logging
import os

logger = logging.getLogger("queue_service")

_READY = 0  # sentinel pushed into a client's channel when their slot opens


class QueueService:
    def __init__(self, pcs_manager):
        self._pcs = pcs_manager
        self._waiting: list[asyncio.Queue] = []
        self._max_viewers = int(os.environ.get("MAX_VIEWERS", "50"))
        # Track "ready" signals sent but not yet reflected in pcs_manager so we
        # don't over-promote when multiple clients are waiting.
        self._pending = 0
        self._last_peer_count = len(pcs_manager.pcs)
        pcs_manager.on_change(self._on_peer_change)

    @property
    def max_viewers(self) -> int:
        return self._max_viewers

    def _occupied(self) -> int:
        return len(self._pcs.pcs) + self._pending

    def slot_available(self) -> bool:
        return self._occupied() < self._max_viewers

    # ── called by the controller for the immediate-ready path ────────────────

    def reserve(self) -> None:
        """Mark one slot as pending before sending a 'ready' signal."""
        self._pending += 1

    def release(self) -> None:
        """Release a pending reservation (client disconnected or connected)."""
        self._pending = max(0, self._pending - 1)
        self._promote()

    # ── queue lifecycle ──────────────────────────────────────────────────────

    def enqueue(self) -> "asyncio.Queue[int]":
        ch: asyncio.Queue[int] = asyncio.Queue(maxsize=1)
        self._waiting.append(ch)
        return ch

    def dequeue(self, ch: "asyncio.Queue[int]") -> None:
        try:
            self._waiting.remove(ch)
        except ValueError:
            # ch was already promoted; cancel that pending reservation and
            # re-check the queue so the next waiter isn't stuck.
            self.release()
        else:
            self._push_positions()

    def position_of(self, ch: "asyncio.Queue[int]") -> int:
        """1-based queue position, or 0 if the client has already been promoted."""
        try:
            return self._waiting.index(ch) + 1
        except ValueError:
            return 0

    # ── internal ─────────────────────────────────────────────────────────────

    def _on_peer_change(self) -> None:
        current = len(self._pcs.pcs)
        delta = current - self._last_peer_count
        self._last_peer_count = current

        if delta > 0:
            # Peer(s) connected → each one resolves a pending slot
            self._pending = max(0, self._pending - delta)

        self._promote()

    def _promote(self) -> None:
        while self._waiting and self._occupied() < self._max_viewers:
            first = self._waiting.pop(0)
            self._put(first, _READY)
            self._pending += 1
        self._push_positions()

    def _push_positions(self) -> None:
        for i, ch in enumerate(self._waiting):
            self._put(ch, i + 1)

    @staticmethod
    def _put(ch: "asyncio.Queue[int]", value: int) -> None:
        """Drain any stale value then place the new one (non-blocking)."""
        while not ch.empty():
            try:
                ch.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            ch.put_nowait(value)
        except asyncio.QueueFull:
            pass
