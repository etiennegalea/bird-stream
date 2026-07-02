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
