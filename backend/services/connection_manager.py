import asyncio
import logging
from typing import List

from aiortc import RTCPeerConnection

logger = logging.getLogger("connection_manager")


class ConnectionManager:
    def __init__(self):
        self.pcs: dict[str, RTCPeerConnection] = {}

    def add_peer(self, peer_id: str, pc: RTCPeerConnection) -> None:
        self.pcs[peer_id] = pc
        logger.info(f"Added peer {peer_id} -> {pc} ({pc.connectionState})")

    def get_peer(self, peer_id: str) -> RTCPeerConnection | None:
        return self.pcs.get(peer_id)

    def get_peers(self, verbose: bool = False) -> dict | List[str]:
        if verbose:
            return {
                key: {
                    "connection_state": value.connectionState,
                    "ice_connection_state": value.iceConnectionState,
                    "ice_gathering_state": value.iceGatheringState,
                    "local_description": str(value.localDescription)
                    if value.localDescription
                    else None,
                    "remote_description": str(value.remoteDescription)
                    if value.remoteDescription
                    else None,
                    "sctp": str(value.sctp) if value.sctp else None,
                    "signalingState": value.signalingState,
                }
                for key, value in self.pcs.items()
            }
        return list(self.pcs.keys())

    def get_pcs(self):
        return self.pcs.values()

    async def remove_peer(self, peer_id: str, pc: RTCPeerConnection) -> None:
        if peer_id in self.pcs:
            for track in pc.getTransceivers():
                if track.receiver and track.receiver.track:
                    track.receiver.track.stop()
            await pc.close()
            removed_pc = self.pcs.pop(peer_id, None)
            logger.info(
                f"Removing peer {peer_id} -> {removed_pc} ({removed_pc.connectionState})"
            )
        else:
            logger.warning(f"Peer not found: {peer_id} -> {pc}")

    async def clean_up(self) -> None:
        try:
            close_coros = []
            for peer_id, pc in list(self.pcs.items()):
                for transceiver in pc.getTransceivers():
                    if transceiver.receiver and transceiver.receiver.track:
                        transceiver.receiver.track.stop()

                if pc.connectionState != "closed":
                    close_coros.append(pc.close())
                    logger.info(f"Closing peer connection: {peer_id}")

            if close_coros:
                await asyncio.gather(*close_coros, return_exceptions=True)

            self.pcs.clear()
            logger.info("All connections cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
