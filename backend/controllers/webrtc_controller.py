import logging

from litestar import Controller, get, post
from litestar.datastructures import State

from models.datastructures import ClientModel
from services.webrtc_service import handle_offer, pcs_manager, get_webrtc_config

logger = logging.getLogger("webrtc_controller")


class WebRTCController(Controller):
    path = "/webrtc"
    tags = ["webrtc"]

    @post("/offer")
    async def offer(self, data: ClientModel, state: State) -> dict:
        # `data` is decoded and validated from the JSON body by Litestar
        # (native msgspec.Struct support); malformed input yields a 422
        # automatically, so no manual decode/try-except is needed.
        return await handle_offer(data, state.audio, state.video)

    @get("/getpeers")
    async def get_peers(self, verbose: bool = False) -> dict | list[str]:
        return pcs_manager.get_peers(verbose=verbose)

    @get("/config", sync_to_thread=False)
    def webrtc_config(self) -> dict:
        return get_webrtc_config()
