import logging
from typing import List
from aiortc import RTCPeerConnection
import asyncio



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("connection_manager")

class ConnectionManager():
    def __init__(self):
        self.pcs = {}
        self.streams = {}

    def add_peer(self, peer_id: str, pc: RTCPeerConnection):
        self.pcs[peer_id] = pc
        logger.info(f"Added peer {peer_id} -> {pc} ({pc.connectionState})")

    def get_peer(self, peer_id: str) -> RTCPeerConnection:
        return self.pcs.get(peer_id, None)
    
    def get_peers(self, verbose:bool=False) -> dict | List[str]:
        if verbose:
            return {key: {
                'connection_state': value.connectionState,
                'ice_connection_state': value.iceConnectionState,
                'ice_gathering_state': value.iceGatheringState,
                'local_description': str(value.localDescription) if value.localDescription else None,
                'remote_description': str(value.remoteDescription) if value.remoteDescription else None,
                'sctp': str(value.sctp) if value.sctp else None,
                'signalingState': value.signalingState
            } for key, value in self.pcs.items()}
        return list(self.pcs.keys())
    
    def get_pcs(self) -> dict:
        return self.pcs.values()
    
    async def remove_peer(self, peer_id: str, pc: RTCPeerConnection):
        if peer_id in self.pcs.keys():
            await pc.close()
            removed_pc = self.pcs.pop(peer_id, None)
            print(f":::: {removed_pc} ::::")
            logger.info(f"Removing peer {peer_id} -> {removed_pc} ({removed_pc.connectionState})")
        else:
            logger.warning(f"Peer not found: {peer_id} -> {pc}")
    

    # Clean up connections
    async def clean_up(self):
        self.pcs.clear()
        logger.info(f"All connections cleaned up: {self.pcs}")
