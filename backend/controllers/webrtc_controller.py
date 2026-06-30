import logging

from litestar import Controller, get, post
from litestar.connection import Request
from litestar.datastructures import State
from litestar.exceptions import ValidationException

import services.auth_service as auth_svc
from models.datastructures import ClientModel
from services.webrtc_service import handle_offer, pcs_manager, get_webrtc_config

logger = logging.getLogger("webrtc_controller")


def _get_user_id(request: Request) -> int | None:
    """Best-effort JWT decode. Anonymous viewers are allowed, so this never raises."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    payload = auth_svc.decode_jwt(header[7:])
    return int(payload["sub"]) if payload else None


def _get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class WebRTCController(Controller):
    path = "/webrtc"
    tags = ["webrtc"]

    @post("/offer")
    async def offer(self, data: ClientModel, request: Request, state: State) -> dict:
        if not data.offer.sdp:
            raise ValidationException("offer.sdp cannot be empty")
        user_id = _get_user_id(request)
        client_ip = _get_client_ip(request) if user_id is not None else None
        return await handle_offer(
            data, state.audio, state.video,
            db_factory=state.db, user_id=user_id, client_ip=client_ip,
        )

    @get("/getpeers")
    async def get_peers(self, verbose: bool = False) -> dict | list[str]:
        return pcs_manager.get_peers(verbose=verbose)

    @get("/config", sync_to_thread=False)
    def webrtc_config(self) -> dict:
        return get_webrtc_config()
