import logging
import re

from litestar import Controller, post
from litestar.datastructures import State
from litestar.exceptions import HTTPException

import services.auth_service as auth_svc
from models.datastructures import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from services.email_service import send_password_reset_email, send_verification_email

logger = logging.getLogger("auth_controller")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    async def login(self, data: LoginRequest, state: State) -> dict:
        token, user_dict, error = await auth_svc.login_user(state.db, data.email, data.password)
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

