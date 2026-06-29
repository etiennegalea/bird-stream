import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import anyio
import jwt
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from models.orm import AuthToken, User

logger = logging.getLogger("auth_service")

_JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "change-me-in-production")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_DAYS = int(os.environ.get("JWT_EXPIRY_DAYS", "7"))
_PBKDF2_ITERATIONS = 260_000
_EMAIL_VERIFY_HOURS = 24
_PASSWORD_RESET_HOURS = 1


# ── password hashing ──────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"{salt}:{digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split(":", 1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
        return digest.hex() == digest_hex
    except Exception:
        return False


# Run in a thread to avoid blocking the event loop during CPU-intensive hashing.
async def hash_password(password: str) -> str:
    return await anyio.to_thread.run_sync(lambda: _hash_password(password))


async def verify_password(password: str, stored: str) -> bool:
    return await anyio.to_thread.run_sync(lambda: _verify_password(password, stored))


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_jwt(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "username": user.username,
        "exp": datetime.now(timezone.utc) + timedelta(days=_JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ── auth operations ───────────────────────────────────────────────────────────

async def register_user(
    db_factory: sessionmaker,
    email: str,
    username: str,
    password: str,
) -> tuple[dict | None, str]:
    """
    Returns (user_info, error). On success error is ''.
    user_info: { id, email, username, verify_token }
    """
    email = email.lower().strip()
    username = username.strip()[:50]

    with db_factory() as session:
        exists = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if exists:
            return None, "Email already registered"

        hashed = await hash_password(password)
        user = User(email=email, username=username, hashed_password=hashed)
        session.add(user)
        session.flush()  # assigns user.id

        verify_token = secrets.token_urlsafe(48)
        session.add(AuthToken(
            user_id=user.id,
            token=verify_token,
            token_type="email_verification",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=_EMAIL_VERIFY_HOURS),
        ))
        session.commit()

        return {"id": user.id, "email": email, "username": username, "verify_token": verify_token}, ""


async def login_user(
    db_factory: sessionmaker,
    email: str,
    password: str,
) -> tuple[str | None, dict | None, str]:
    """
    Returns (jwt_token, user_dict, error). On success error is ''.
    """
    email = email.lower().strip()

    with db_factory() as session:
        user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if not user:
            return None, None, "Invalid email or password"

        if not await verify_password(password, user.hashed_password):
            return None, None, "Invalid email or password"

        if not user.is_verified:
            return None, None, "Please verify your email before logging in"

        token = create_jwt(user)
        user_dict = {"id": user.id, "email": user.email, "username": user.username, "is_verified": user.is_verified}
        return token, user_dict, ""


def verify_email_token(db_factory: sessionmaker, token: str) -> tuple[bool, str]:
    """Returns (success, error)."""
    now = datetime.now(timezone.utc)
    with db_factory() as session:
        auth_token = session.execute(
            select(AuthToken).where(
                AuthToken.token == token,
                AuthToken.token_type == "email_verification",
            )
        ).scalar_one_or_none()

        if not auth_token:
            return False, "Invalid token"
        if auth_token.used_at is not None:
            return False, "Token already used"
        if auth_token.expires_at.replace(tzinfo=timezone.utc) < now:
            return False, "Token expired"

        auth_token.used_at = now
        auth_token.user.is_verified = True
        session.commit()
        return True, ""


def create_password_reset_token(
    db_factory: sessionmaker,
    email: str,
) -> tuple[dict | None, str]:
    """
    Returns (user_info, reset_token) or (None, '') if email not found
    (caller always returns 200 to prevent enumeration).
    """
    email = email.lower().strip()
    with db_factory() as session:
        user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if not user:
            return None, ""

        reset_token = secrets.token_urlsafe(48)
        session.add(AuthToken(
            user_id=user.id,
            token=reset_token,
            token_type="password_reset",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=_PASSWORD_RESET_HOURS),
        ))
        session.commit()
        return {"email": email, "username": user.username}, reset_token


async def reset_password(
    db_factory: sessionmaker,
    token: str,
    new_password: str,
) -> tuple[bool, str]:
    """Returns (success, error)."""
    now = datetime.now(timezone.utc)
    with db_factory() as session:
        auth_token = session.execute(
            select(AuthToken).where(
                AuthToken.token == token,
                AuthToken.token_type == "password_reset",
            )
        ).scalar_one_or_none()

        if not auth_token:
            return False, "Invalid token"
        if auth_token.used_at is not None:
            return False, "Token already used"
        if auth_token.expires_at.replace(tzinfo=timezone.utc) < now:
            return False, "Token expired"

        hashed = await hash_password(new_password)
        auth_token.used_at = now
        auth_token.user.hashed_password = hashed
        session.commit()
        return True, ""
