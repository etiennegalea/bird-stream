"""MediaMTX external auth hook.

MediaMTX (authMethod: http) POSTs here for every publish/read attempt.
2xx = allow, anything else = deny.

Payload (MediaMTX v1.x):
    {"user": "", "password": "", "token": "", "ip": "",
     "action": "publish|read|api|...", "path": "",
     "protocol": "srt|webrtc|hls|...", "id": "", "query": ""}

Env:
    MEDIAMTX_PUBLISH_USER / MEDIAMTX_PUBLISH_PASSWORD  — SRT publish creds (the Pi)
    MEDIAMTX_REQUIRE_READ_AUTH — "true" to require a valid account JWT
    (?jwt=...) for viewers while the stream is public; default allows anonymous
    reads. Private mode always requires a short-lived admin stream token.
"""

import logging
import os
from urllib.parse import parse_qs

from litestar import Controller, post
from litestar.exceptions import HTTPException

import services.auth_service as auth_svc
from services.stream_settings_service import stream_settings

logger = logging.getLogger("mediamtx_controller")

_PUBLISH_ACTIONS = {"publish"}
_READ_ACTIONS = {"read", "playback"}


def _require_read_auth() -> bool:
    return os.environ.get("MEDIAMTX_REQUIRE_READ_AUTH", "false").lower() == "true"


def _check_publish(user: str, password: str) -> bool:
    expected_user = os.environ.get("MEDIAMTX_PUBLISH_USER", "picam")
    expected_pass = os.environ.get("MEDIAMTX_PUBLISH_PASSWORD")
    if not expected_pass:
        logger.error("MEDIAMTX_PUBLISH_PASSWORD not set — denying publish")
        return False
    return user == expected_user and password == expected_pass


def _check_read(
    query: str,
    *,
    bearer_token: str | None = None,
    admin_only: bool = False,
) -> bool:
    if not admin_only and not _require_read_auth():
        return True
    token = bearer_token or (parse_qs(query or "").get("jwt") or [None])[0]
    if not token:
        return False
    if admin_only:
        return auth_svc.decode_stream_access_token(token) is not None
    return (
        auth_svc.decode_jwt(token) is not None
        or auth_svc.decode_stream_access_token(token) is not None
    )


async def authenticate_request(data: dict) -> None:
    """Core MediaMTX auth decision. Returns None to allow, raises HTTPException
    to deny. Kept as a plain module-level function so it's unit-testable
    without instantiating the Litestar Controller."""
    action = data.get("action", "")
    path = data.get("path", "")
    protocol = data.get("protocol", "")
    ip = data.get("ip", "")

    if action in _PUBLISH_ACTIONS:
        if _check_publish(data.get("user") or "", data.get("password") or ""):
            logger.info(f"Allow publish path={path} proto={protocol} ip={ip}")
            return
        logger.warning(f"Deny publish path={path} proto={protocol} ip={ip}")
        raise HTTPException(status_code=401, detail="Publish not authorized")

    if action in _READ_ACTIONS:
        # RTSP is only reachable inside the docker network (port 8554 is
        # not published) — used by the detection worker, always allowed.
        if protocol == "rtsp":
            logger.debug(f"Allow internal rtsp read path={path} ip={ip}")
            return
        # Admin kill-switch: while both video and audio are disabled, no
        # new viewer sessions may start. (Per-track blocking of a live
        # session is enforced client-side via /stream-settings.)
        if stream_settings.fully_blocked():
            logger.warning(f"Deny read (stream disabled by admin) path={path} proto={protocol} ip={ip}")
            raise HTTPException(status_code=401, detail="Stream disabled by admin")
        if _check_read(
            data.get("query") or "",
            bearer_token=data.get("token") or None,
            admin_only=stream_settings.private_enabled,
        ):
            logger.debug(f"Allow read path={path} proto={protocol} ip={ip}")
            return
        logger.warning(f"Deny read path={path} proto={protocol} ip={ip}")
        raise HTTPException(status_code=401, detail="Viewer not authorized")

    # Control API: port 9997 is never published, only reachable on the
    # docker network (backend peer-count polling) — allow.
    if action == "api":
        return

    # metrics / pprof / playback listing — deny by default
    logger.warning(f"Deny action={action} path={path} ip={ip}")
    raise HTTPException(status_code=401, detail="Not authorized")


class MediaMTXController(Controller):
    path = "/mediamtx"
    tags = ["mediamtx"]

    @post("/auth", status_code=204)
    async def authenticate(self, data: dict) -> None:
        await authenticate_request(data)
