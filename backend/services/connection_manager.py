import asyncio
import logging
from typing import Callable, List

from aiortc import RTCPeerConnection

logger = logging.getLogger("connection_manager")


class ConnectionManager:
    def __init__(self):
        self.pcs: dict[str, RTCPeerConnection] = {}
        self._change_listeners: list[Callable[[], None]] = []

    def on_change(self, callback: Callable[[], None]) -> None:
        self._change_listeners.append(callback)

    def remove_change_listener(self, callback: Callable[[], None]) -> None:
        try:
            self._change_listeners.remove(callback)
        except ValueError:
            pass

    def _notify_change(self) -> None:
        for cb in self._change_listeners[:]:  # copy: a callback may mutate the list
            cb()

    async def add_peer(self, peer_id: str, pc: RTCPeerConnection) -> None:
        if peer_id in self.pcs:
            old_pc = self.pcs.pop(peer_id)
            if old_pc.connectionState != "closed":
                logger.info(f"Closing stale connection for peer {peer_id} before replacing")
                await old_pc.close()
        self.pcs[peer_id] = pc
        logger.info(f"Added peer {peer_id} ({pc.connectionState})")
        self._notify_change()

    def get_peer(self, peer_id: str) -> RTCPeerConnection | None:
        return self.pcs.get(peer_id)

    def get_peers(self, verbose: bool = False) -> dict | List[str]:
        if verbose:
            return {
                key: {
                    "connection_state": value.connectionState,
                    "ice_connection_state": value.iceConnectionState,
                    "ice_gathering_state": value.iceGatheringState,
                    "local_description": str(value.localDescription) if value.localDescription else None,
                    "remote_description": str(value.remoteDescription) if value.remoteDescription else None,
                    "sctp": str(value.sctp) if value.sctp else None,
                    "signalingState": value.signalingState,
                }
                for key, value in self.pcs.items()
            }
        return list(self.pcs.keys())

    def get_pcs(self):
        return self.pcs.values()

    async def remove_peer(self, peer_id: str, pc: RTCPeerConnection) -> None:
        # Guard: only remove if the stored PC is the one we're closing.
        # A reload may have already replaced this peer_id with a new PC.
        if self.pcs.get(peer_id) is not pc:
            logger.info(f"Skipping remove for {peer_id}: stored PC has already been replaced")
            return
        for transceiver in pc.getTransceivers():
            if transceiver.receiver and transceiver.receiver.track:
                transceiver.receiver.track.stop()
        await pc.close()
        self.pcs.pop(peer_id, None)
        logger.info(f"Removed peer {peer_id} ({pc.connectionState})")
        self._notify_change()

    async def clean_up(self) -> None:
        try:
            close_coros = [
                pc.close()
                for pc in self.pcs.values()
                if pc.connectionState != "closed"
            ]
            if close_coros:
                await asyncio.gather(*close_coros, return_exceptions=True)
            self.pcs.clear()
            self._notify_change()
            logger.info("All peer connections cleaned up")
        except Exception:
            logger.exception("Error during cleanup")
