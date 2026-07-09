import logging

import msgspec
from litestar import Controller, get, post
from litestar.connection import Request
from litestar.datastructures import State
from litestar.exceptions import HTTPException
from sqlalchemy import select

import services.auth_service as auth_svc
from controllers.chat_controller import chat_service
from models.orm import User
from services.mqtt_service import mqtt_devices
from services.stream_settings_service import stream_settings
from services.webrtc_service import pcs_manager

logger = logging.getLogger("admin_controller")


def _require_admin(request: Request, db_factory) -> int:
    """Extract user_id from Bearer token and verify admin status in DB."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = auth_svc.decode_jwt(header[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = int(payload["sub"])
    with db_factory() as session:
        user = session.get(User, user_id)
        if not user or not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


class BlockIpRequest(msgspec.Struct):
    ip: str


class StreamSettingsRequest(msgspec.Struct):
    video_enabled: bool | None = None
    audio_enabled: bool | None = None


class AdminController(Controller):
    path = "/admin"
    tags = ["admin"]

    @get("/users")
    async def get_users(self, request: Request, state: State) -> dict:
        _require_admin(request, state.db)

        data = chat_service.get_connected_users()

        # Enrich account users with DB details (email, avatar, last_ip, watching_stream).
        user_ids = [a["user_id"] for a in data["accounts"] if a["user_id"] is not None]
        db_users: dict[int, User] = {}
        if user_ids:
            with state.db() as session:
                rows = session.execute(
                    select(User).where(User.id.in_(user_ids))
                ).scalars().all()
                db_users = {u.id: u for u in rows}

        watching_user_ids: set[int] = set(pcs_manager.user_peers.keys())

        enriched_accounts = []
        for entry in data["accounts"]:
            uid = entry["user_id"]
            db_user = db_users.get(uid) if uid else None
            enriched_accounts.append({
                "user_id": uid,
                "username": entry["username"],
                "email": db_user.email if db_user else None,
                "avatar": db_user.avatar if db_user else None,
                "chat_ip": entry["ip"],
                "last_ip": db_user.last_ip if db_user else None,
                "watching_stream": uid in watching_user_ids if uid else False,
            })

        return {
            "accounts": enriched_accounts,
            "guests": data["guests"],
            "blocked_ips": data["blocked_ips"],
        }

    @post("/block-ip")
    async def block_ip(self, request: Request, data: BlockIpRequest, state: State) -> dict:
        _require_admin(request, state.db)
        ip = data.ip.strip()
        if not ip:
            raise HTTPException(status_code=400, detail="IP address required")
        closed = await chat_service.block_ip(ip)
        logger.info("Admin blocked IP %s (%d connections closed)", ip, closed)
        return {"blocked": ip, "connections_closed": closed}

    @post("/unblock-ip")
    async def unblock_ip(self, request: Request, data: BlockIpRequest, state: State) -> dict:
        _require_admin(request, state.db)
        ip = data.ip.strip()
        chat_service.unblock_ip(ip)
        logger.info("Admin unblocked IP %s", ip)
        return {"unblocked": ip}

    @get("/stream-settings")
    async def get_stream_settings(self, request: Request, state: State) -> dict:
        _require_admin(request, state.db)
        return stream_settings.snapshot()

    @post("/stream-settings")
    async def update_stream_settings(
        self, request: Request, data: StreamSettingsRequest, state: State
    ) -> dict:
        user_id = _require_admin(request, state.db)
        if data.video_enabled is None and data.audio_enabled is None:
            raise HTTPException(status_code=400, detail="No settings provided")
        settings = stream_settings.update(
            video_enabled=data.video_enabled,
            audio_enabled=data.audio_enabled,
        )
        logger.info("Admin (user_id=%s) set stream settings: %s", user_id, settings)
        return settings

    # ── Pi transmitter control (MQTT bridge) ─────────────────────────────

    @get("/stream/devices")
    async def get_stream_devices(self, request: Request, state: State) -> dict:
        """Latest retained/heartbeat status of every known transmitter."""
        _require_admin(request, state.db)
        return {
            "broker_connected": mqtt_devices.is_connected(),
            "devices": mqtt_devices.devices(),
        }

    @post("/stream/devices/{pi_id:str}/{action:str}")
    async def control_stream_device(
        self, request: Request, state: State, pi_id: str, action: str
    ) -> dict:
        user_id = _require_admin(request, state.db)
        try:
            mqtt_devices.send_control(pi_id, action)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        logger.info("Admin (user_id=%s) sent '%s' to device '%s'",
                    user_id, action, pi_id)
        return {"ok": True, "pi_id": pi_id, "action": action}
