import logging
import re

import msgspec
from litestar import Controller, delete, get, post
from litestar.connection import Request
from litestar.datastructures import State
from litestar.exceptions import HTTPException
from sqlalchemy import select

import services.auth_service as auth_svc
from controllers.chat_controller import chat_service
from models.orm import User
from services.admin_action_service import (
    list_admin_actions,
    record_admin_action,
    record_admin_action_with_factory,
)
from services.mqtt_service import mqtt_devices
from services.camera_automation_service import camera_automation
from services.stream_settings_service import stream_settings
from services.webrtc_service import pcs_manager

logger = logging.getLogger("admin_controller")

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")  # 00:00–23:59


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
        if not user or user.is_blocked or not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


class BlockIpRequest(msgspec.Struct):
    ip: str


class BlockUserRequest(msgspec.Struct):
    is_blocked: bool


class StreamSettingsRequest(msgspec.Struct):
    video_enabled: bool | None = None
    audio_enabled: bool | None = None
    private_enabled: bool | None = None


class ScheduleRequest(msgspec.Struct):
    enabled: bool
    mode: str | None = None   # "sun" (sunrise–sunset) or "fixed"
    start: str | None = None  # "HH:MM" local Pi time (fixed mode / sun fallback)
    end: str | None = None
    latitude: float | None = None   # sun mode: override IP geolocation
    longitude: float | None = None


class CameraEnabledRequest(msgspec.Struct):
    enabled: bool


class CameraAutomationRequest(msgspec.Struct):
    auto_manage_pov: bool
    bird_triggered_pov: bool = False


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
        with state.db() as session:
            if user_ids:
                rows = session.execute(
                    select(User).where(User.id.in_(user_ids))
                ).scalars().all()
                db_users = {u.id: u for u in rows}
            blocked_users = session.execute(
                select(User).where(User.is_blocked.is_(True))
                .order_by(User.username)
            ).scalars().all()

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
                "is_blocked": db_user.is_blocked if db_user else False,
                "watching_stream": uid in watching_user_ids if uid else False,
            })

        return {
            "accounts": enriched_accounts,
            "guests": data["guests"],
            "blocked_ips": data["blocked_ips"],
            "blocked_users": [
                {
                    "user_id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "last_ip": user.last_ip,
                    "is_blocked": True,
                }
                for user in blocked_users
            ],
        }

    @get("/actions")
    async def get_admin_actions(
        self, request: Request, state: State, limit: int = 100
    ) -> dict:
        _require_admin(request, state.db)
        return {"actions": list_admin_actions(state.db, limit)}

    @delete("/chat/messages/{message_id:int}", status_code=200)
    async def delete_chat_message(
        self, request: Request, state: State, message_id: int
    ) -> dict:
        admin_id = _require_admin(request, state.db)
        result, error = await chat_service.soft_delete_message(
            state.db, message_id, admin_id
        )
        if error:
            status = 404 if error == "Message not found" else 409
            raise HTTPException(status_code=status, detail=error)
        return result

    @post("/users/{user_id:int}/blocked")
    async def set_user_blocked(
        self,
        request: Request,
        state: State,
        user_id: int,
        data: BlockUserRequest,
    ) -> dict:
        admin_id = _require_admin(request, state.db)
        if user_id == admin_id and data.is_blocked:
            raise HTTPException(status_code=400, detail="You cannot block yourself")
        with state.db() as session:
            user = session.get(User, user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            user.is_blocked = data.is_blocked
            username = user.username
            record_admin_action(
                session,
                admin_user_id=admin_id,
                action_type=("user.blocked" if data.is_blocked else "user.unblocked"),
                target_type="user",
                target_id=user_id,
                details={"username": username},
            )
            session.commit()
        disconnected = (
            await chat_service.disconnect_user(user_id)
            if data.is_blocked else 0
        )
        logger.info(
            "Admin user_id=%s set blocked=%s for user_id=%s",
            admin_id, data.is_blocked, user_id,
        )
        return {
            "user_id": user_id,
            "username": username,
            "is_blocked": data.is_blocked,
            "connections_closed": disconnected,
        }

    @post("/block-ip")
    async def block_ip(self, request: Request, data: BlockIpRequest, state: State) -> dict:
        admin_id = _require_admin(request, state.db)
        ip = data.ip.strip()
        if not ip:
            raise HTTPException(status_code=400, detail="IP address required")
        closed = await chat_service.block_ip(ip)
        record_admin_action_with_factory(
            state.db,
            admin_user_id=admin_id,
            action_type="ip.blocked",
            target_type="ip_address",
            target_id=ip,
            details={"connections_closed": closed},
        )
        logger.info("Admin blocked IP %s (%d connections closed)", ip, closed)
        return {"blocked": ip, "connections_closed": closed}

    @post("/unblock-ip")
    async def unblock_ip(self, request: Request, data: BlockIpRequest, state: State) -> dict:
        admin_id = _require_admin(request, state.db)
        ip = data.ip.strip()
        chat_service.unblock_ip(ip)
        record_admin_action_with_factory(
            state.db,
            admin_user_id=admin_id,
            action_type="ip.unblocked",
            target_type="ip_address",
            target_id=ip,
        )
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
        if (
            data.video_enabled is None
            and data.audio_enabled is None
            and data.private_enabled is None
        ):
            raise HTTPException(status_code=400, detail="No settings provided")
        settings = stream_settings.update(
            video_enabled=data.video_enabled,
            audio_enabled=data.audio_enabled,
            private_enabled=data.private_enabled,
            db_factory=state.db,
        )
        record_admin_action_with_factory(
            state.db,
            admin_user_id=user_id,
            action_type="stream.settings_updated",
            target_type="stream_settings",
            target_id="global",
            details=settings,
        )
        logger.info("Admin (user_id=%s) set stream settings: %s", user_id, settings)
        return settings

    @post("/stream-access-token")
    async def create_stream_access_token(
        self, request: Request, state: State
    ) -> dict:
        """Issue a short-lived MediaMTX read token to a verified admin."""
        user_id = _require_admin(request, state.db)
        record_admin_action_with_factory(
            state.db,
            admin_user_id=user_id,
            action_type="stream.access_token_issued",
            target_type="user",
            target_id=user_id,
        )
        return {
            "token": auth_svc.create_stream_access_token(user_id),
            "expires_in": auth_svc.stream_access_token_lifetime_seconds(),
        }

    # ── Pi transmitter control (MQTT bridge) ─────────────────────────────

    @get("/stream/devices")
    async def get_stream_devices(self, request: Request, state: State) -> dict:
        """Latest retained/heartbeat status of every known transmitter."""
        _require_admin(request, state.db)
        devices = mqtt_devices.devices()
        for device in devices:
            device["camera_automation"] = camera_automation.describe_device(device)
        return {
            "broker_connected": mqtt_devices.is_connected(),
            "devices": devices,
        }

    @post("/stream/devices/{pi_id:str}/camera-automation")
    async def set_camera_automation(
        self, request: Request, state: State, pi_id: str,
        data: CameraAutomationRequest,
    ) -> dict:
        user_id = _require_admin(request, state.db)
        # Reuse MQTT's strict identifier validation even though saving the
        # preference itself does not require a live broker connection.
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pi_id or ""):
            raise HTTPException(status_code=400, detail="Invalid device id")
        settings = camera_automation.update(
            pi_id,
            auto_manage_pov=data.auto_manage_pov,
            bird_triggered_pov=data.bird_triggered_pov,
            db_factory=state.db,
        )
        record_admin_action_with_factory(
            state.db,
            admin_user_id=user_id,
            action_type="device.camera_automation_updated",
            target_type="device",
            target_id=pi_id,
            details=settings,
        )
        logger.info(
            "Admin (user_id=%s) set camera automation on '%s': %s",
            user_id, pi_id, settings,
        )
        return {"ok": True, "pi_id": pi_id, **settings}

    @post("/stream/devices/{pi_id:str}/schedule")
    async def set_device_schedule(
        self, request: Request, state: State, pi_id: str, data: ScheduleRequest
    ) -> dict:
        """Set the daily broadcast window on a transmitter. Outside the window
        the device rests (idle). Times are the Pi's local time, "HH:MM"."""
        user_id = _require_admin(request, state.db)
        mode = data.mode or "sun"
        if mode not in ("sun", "fixed"):
            raise HTTPException(status_code=400,
                                detail="mode must be 'sun' or 'fixed'")
        params: dict = {"enabled": data.enabled, "mode": mode}
        if data.start is not None:
            params["start"] = data.start
        if data.end is not None:
            params["end"] = data.end
        if data.latitude is not None:
            params["latitude"] = data.latitude
        if data.longitude is not None:
            params["longitude"] = data.longitude
        # Fixed mode requires valid clock times; sun mode derives them.
        if data.enabled and mode == "fixed":
            for key in ("start", "end"):
                val = params.get(key)
                if not (isinstance(val, str) and _HHMM_RE.match(val)):
                    raise HTTPException(
                        status_code=400,
                        detail=f"{key} must be 'HH:MM' (00:00–23:59)")
        try:
            mqtt_devices.send_control(pi_id, "set_schedule", params=params)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        record_admin_action_with_factory(
            state.db,
            admin_user_id=user_id,
            action_type="device.schedule_updated",
            target_type="device",
            target_id=pi_id,
            details=params,
        )
        logger.info("Admin (user_id=%s) set schedule on '%s': %s",
                    user_id, pi_id, params)
        return {"ok": True, "pi_id": pi_id, "schedule": params}

    @post("/stream/devices/{pi_id:str}/{action:str}")
    async def control_stream_device(
        self, request: Request, state: State, pi_id: str, action: str
    ) -> dict:
        user_id = _require_admin(request, state.db)
        # This route is only for immediate start/stop; scheduling has its own
        # endpoint (with a validated body) above.
        if action not in {"start", "stop"}:
            raise HTTPException(
                status_code=400, detail="Action must be 'start' or 'stop'")
        try:
            mqtt_devices.send_control(pi_id, action)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        record_admin_action_with_factory(
            state.db,
            admin_user_id=user_id,
            action_type=f"device.{action}",
            target_type="device",
            target_id=pi_id,
        )
        logger.info("Admin (user_id=%s) sent '%s' to device '%s'",
                    user_id, action, pi_id)
        return {"ok": True, "pi_id": pi_id, "action": action}

    @post("/stream/devices/{pi_id:str}/cameras/{camera_id:str}/{action:str}")
    async def control_stream_camera(
        self, request: Request, state: State, pi_id: str, camera_id: str,
        action: str,
    ) -> dict:
        user_id = _require_admin(request, state.db)
        if action not in {"start", "stop"}:
            raise HTTPException(
                status_code=400, detail="Action must be 'start' or 'stop'")
        try:
            mqtt_devices.send_control(
                pi_id, action, params={"camera_id": camera_id})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        record_admin_action_with_factory(
            state.db,
            admin_user_id=user_id,
            action_type=f"camera.{action}",
            target_type="camera",
            target_id=f"{pi_id}/{camera_id}",
            details={"pi_id": pi_id, "camera_id": camera_id},
        )
        logger.info(
            "Admin (user_id=%s) sent '%s' to camera '%s/%s'",
            user_id, action, pi_id, camera_id)
        return {
            "ok": True, "pi_id": pi_id, "camera_id": camera_id,
            "action": action,
        }

    @post("/stream/devices/{pi_id:str}/cameras/{camera_id:str}/enabled")
    async def set_stream_camera_enabled(
        self, request: Request, state: State, pi_id: str, camera_id: str,
        data: CameraEnabledRequest,
    ) -> dict:
        user_id = _require_admin(request, state.db)
        try:
            mqtt_devices.send_control(
                pi_id,
                "set_camera_enabled",
                params={"camera_id": camera_id, "enabled": data.enabled},
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        record_admin_action_with_factory(
            state.db,
            admin_user_id=user_id,
            action_type="camera.enabled_updated",
            target_type="camera",
            target_id=f"{pi_id}/{camera_id}",
            details={
                "pi_id": pi_id,
                "camera_id": camera_id,
                "enabled": data.enabled,
            },
        )
        logger.info(
            "Admin (user_id=%s) set camera '%s/%s' enabled=%s",
            user_id, pi_id, camera_id, data.enabled)
        return {
            "ok": True, "pi_id": pi_id, "camera_id": camera_id,
            "enabled": data.enabled,
        }
