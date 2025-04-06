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
            for track in pc.getTransceivers():
                if track.receiver and track.receiver.track:
                    track.receiver.track.stop()
            await pc.close()
            removed_pc = self.pcs.pop(peer_id, None)
            print(f":::: {removed_pc} ::::")
            logger.info(f"Removing peer {peer_id} -> {removed_pc} ({removed_pc.connectionState})")
        else:
            logger.warning(f"Peer not found: {peer_id} -> {pc}")
    

    # Clean up connections
    async def clean_up(self):
        try:
            close_coros = []
            for peer_id, pc in list(self.pcs.items()):
                # Stop all tracks first
                for transceiver in pc.getTransceivers():
                    if transceiver.receiver and transceiver.receiver.track:
                        transceiver.receiver.track.stop()
                
                # Force connection state to closed
                if pc.connectionState != "closed":
                    close_coros.append(pc.close())
                    logger.info(f"Closing peer connection: {peer_id}")
            
            if close_coros:
                await asyncio.gather(*close_coros, return_exceptions=True)
            
            self.pcs.clear()
            logger.info("All connections cleaned up")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")