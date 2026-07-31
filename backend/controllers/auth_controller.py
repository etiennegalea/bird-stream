import logging
import re

from litestar import Controller, delete, get, patch, post
from litestar.connection import Request
from litestar.datastructures import State
from litestar.exceptions import HTTPException

import services.auth_service as auth_svc
from models.datastructures import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UpdateProfileRequest,
    VerifyEmailRequest,
)
from services.email_service import send_password_reset_email, send_verification_email
from services.client_ip import get_client_ip

logger = logging.getLogger("auth_controller")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _require_auth(request: Request) -> int:
    """Extract user_id from Bearer token or raise 401."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = auth_svc.decode_jwt(header[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return int(payload["sub"])


class AuthController(Controller):
    path = "/auth"
    tags = ["auth"]

    @post("/register", status_code=201)
    async def register(self, data: RegisterRequest, state: State) -> dict:
        if not _EMAIL_RE.match(data.email):
            raise HTTPException(status_code=400, detail="Invalid email address")
        if len(data.username.strip()) < 2:
            raise HTTPException(status_code=400, detail="Username must be at least 2 characters")
        if len(data.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

        user_info, error = await auth_svc.register_user(state.db, data.email, data.username, data.password)
        if error:
            raise HTTPException(status_code=409, detail=error)

        await send_verification_email(user_info["email"], user_info["username"], user_info["verify_token"])
        return {"message": f"Verification email sent to {user_info['email']}"}

    @post("/login")
    async def login(self, request: Request, data: LoginRequest, state: State) -> dict:
        token, user_dict, error = await auth_svc.login_user(
            state.db,
            data.identifier,
            data.password,
            client_ip=get_client_ip(request),
        )
        if error:
            code = 403 if "verify" in error else 401
            raise HTTPException(status_code=code, detail=error)
        return {"access_token": token, "token_type": "bearer", "user": user_dict}

    @post("/verify-email")
    async def verify_email(self, data: VerifyEmailRequest, state: State) -> dict:
        success, error = auth_svc.verify_email_token(state.db, data.token)
        if not success:
            raise HTTPException(status_code=400, detail=error)
        return {"message": "Email verified. You can now log in."}

    @post("/forgot-password")
    async def forgot_password(self, data: ForgotPasswordRequest, state: State) -> dict:
        user_info, reset_token = auth_svc.create_password_reset_token(state.db, data.email)
        if user_info and reset_token:
            await send_password_reset_email(user_info["email"], user_info["username"], reset_token)
        # Always return 200 to prevent email enumeration.
        return {"message": "If that email is registered, a password reset link has been sent."}

    @post("/reset-password")
    async def reset_password(self, data: ResetPasswordRequest, state: State) -> dict:
        if len(data.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        success, error = await auth_svc.reset_password(state.db, data.token, data.password)
        if not success:
            raise HTTPException(status_code=400, detail=error)
        return {"message": "Password reset successfully. You can now log in."}

    @get("/profile")
    async def get_profile(self, request: Request, state: State) -> dict:
        user_id = _require_auth(request)
        profile = auth_svc.get_user_profile(state.db, user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        return profile

    @patch("/profile")
    async def update_profile(self, request: Request, data: UpdateProfileRequest, state: State) -> dict:
        user_id = _require_auth(request)
        if data.email is not None and not _EMAIL_RE.match(data.email.strip()):
            raise HTTPException(status_code=400, detail="Invalid email address")
        profile, error = auth_svc.update_user_profile(
            state.db,
            user_id,
            data.email,
            data.username,
            data.bio,
            data.avatar,
            data.bird_notification_email,
            data.auto_join_chat,
            data.profanity_filter_enabled,
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
        return profile

    @post("/change-password")
    async def change_password(self, request: Request, data: ChangePasswordRequest, state: State) -> dict:
        user_id = _require_auth(request)
        success, error = await auth_svc.change_user_password(
            state.db, user_id, data.current_password, data.new_password
        )
        if not success:
            raise HTTPException(status_code=400, detail=error)
        return {"message": "Password changed successfully."}

    @delete("/account", status_code=200)
    async def delete_account(self, request: Request, data: DeleteAccountRequest, state: State) -> dict:
        user_id = _require_auth(request)
        success, error = await auth_svc.delete_user_account(
            state.db, user_id, data.current_password
        )
        if not success:
            status_code = 404 if error == "User not found" else 400
            raise HTTPException(status_code=status_code, detail=error)
        return {"message": "Account deleted successfully."}

    @get("/profile/public/{username:str}")
    async def get_public_profile(self, request: Request, username: str, state: State) -> dict:
        profile = auth_svc.get_public_profile_by_username(
            state.db, username, _viewer_has_filter_off(request, state.db)
        )
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        return profile

    @get("/profile/public/id/{user_id:int}")
    async def get_public_profile_by_id(self, request: Request, user_id: int, state: State) -> dict:
        profile = auth_svc.get_public_profile_by_id(
            state.db, user_id, _viewer_has_filter_off(request, state.db)
        )
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        return profile


def _viewer_has_filter_off(request: Request, db_factory) -> bool:
    """Profanity statistics are omitted unless an authenticated viewer opted out."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return False
    payload = auth_svc.decode_jwt(header[7:])
    if not payload:
        return False
    profile = auth_svc.get_user_profile(db_factory, int(payload["sub"]))
    return bool(profile and not profile["profanity_filter_enabled"])
