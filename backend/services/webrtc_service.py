import logging

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaRelay
from aiortc.rtcrtpsender import RTCRtpSender

import services.auth_service as auth_svc
from models.datastructures import ClientModel
from services.config_service import load_turn_credentials
from services.connection_manager import ConnectionManager
from services.video_service import force_codec

logger = logging.getLogger("webrtc_service")

pcs_manager = ConnectionManager()
relay = MediaRelay()


def get_webrtc_config() -> dict:
    return {
        "pool_size": RTCRtpSender.TRANSPORT_POOL_SIZE,
        "port_min": RTCRtpSender.TRANSPORT_PORT_MIN,
        "port_max": RTCRtpSender.TRANSPORT_PORT_MAX,
        "port_range": RTCRtpSender.TRANSPORT_PORT_MAX
        - RTCRtpSender.TRANSPORT_PORT_MIN
        + 1,
    }


async def handle_offer(
    peer: ClientModel,
    audio,
    video,
    db_factory=None,
    user_id: int | None = None,
    client_ip: str | None = None,
) -> dict:
    turn_username, turn_credential = load_turn_credentials()
    config = RTCConfiguration(
        [
            RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
            RTCIceServer(
                urls=[
                    "turn:turn.lifeofarobin.com:3478?transport=udp",
                    "turns:turn.lifeofarobin.com:5349?transport=udp",
                ],
                username=turn_username,
                credential=turn_credential,
            ),
        ]
    )

    config.iceTransportPolicy = "all"
    config.bundlePolicy = "max-bundle"
    config.rtcpMuxPolicy = "require"
    config.iceConnectionTimeout = 5
    config.iceKeepAliveInterval = 2
    config.iceInactiveTimeout = 3

    pc = RTCPeerConnection(config)
    await pcs_manager.add_peer(peer.id, pc)

    if user_id is not None:
        await pcs_manager.bind_user(user_id, peer.id)
        if db_factory is not None:
            auth_svc.update_last_ip(db_factory, user_id, client_ip)

    if audio:
        audio_sender = pc.addTrack(relay.subscribe(audio))
        logger.info(f"Audio sender created: {audio_sender}")
        force_codec(pc, audio_sender, "audio/opus")

    video_sender = pc.addTrack(relay.subscribe(video))
    logger.info(f"Video sender created: {video_sender}")
    force_codec(pc, video_sender, "video/H264")

    @pc.on("track")
    def on_track(track):
        logger.info(f"Received track: {track.kind}")

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        logger.info(f"ICE connection state changed to: {pc.iceConnectionState}")
        if pc.iceConnectionState in ("failed", "disconnected"):
            try:
                logger.info(f"ICE Connection failed for peer {peer.id}, cleaning up")
                await pcs_manager.remove_peer(peer.id, pc)
            except Exception:
                logger.exception(f"Error (ICE) removing peer: {peer.id}")

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"Connection state changed to {pc.connectionState} for peer {peer.id}")
        if pc.connectionState in ("closed", "failed", "disconnected"):
            try:
                logger.info(f"Cleaning up connection for peer {peer.id}")
                await pcs_manager.remove_peer(peer.id, pc)
            except Exception:
                logger.exception(f"Error removing peer: {peer.id}")

    @pc.on("icecandidate")
    def on_icecandidate(candidate):
        logger.info(f"New ICE candidate: {candidate}")

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=peer.offer.sdp, type=peer.offer.type)
    )
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
    }
