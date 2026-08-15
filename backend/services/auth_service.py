import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import anyio
import jwt
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from models.orm import AuthToken, ChatMessage, User

logger = logging.getLogger("auth_service")

_JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "change-me-in-production")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_DAYS = int(os.environ.get("JWT_EXPIRY_DAYS", "7"))
# Deliberately changes for every backend process. Tokens from an earlier
# process remain correctly signed, but are rejected after a server restart.
_SERVER_SESSION_ID = secrets.token_urlsafe(24)
_STREAM_ACCESS_MINUTES = int(os.environ.get("STREAM_ACCESS_TOKEN_MINUTES", "10"))
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
        "server_session": _SERVER_SESSION_ID,
        "exp": datetime.now(timezone.utc) + timedelta(days=_JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_jwt(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        if payload.get("server_session") != _SERVER_SESSION_ID:
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def create_stream_access_token(user_id: int) -> str:
    """Mint a narrow, short-lived token suitable for a MediaMTX URL query."""
    payload = {
        "sub": str(user_id),
        "scope": "stream:read:admin",
        "server_session": _SERVER_SESSION_ID,
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=_STREAM_ACCESS_MINUTES),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_stream_access_token(token: str) -> dict | None:
    payload = decode_jwt(token)
    if not payload or payload.get("scope") != "stream:read:admin":
        return None
    return payload


def stream_access_token_lifetime_seconds() -> int:
    return _STREAM_ACCESS_MINUTES * 60


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

        exists = session.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()
        if exists:
            return None, "Username already taken"

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
    identifier: str,
    password: str,
    client_ip: str | None = None,
) -> tuple[str | None, dict | None, str]:
    """
    Returns (jwt_token, user_dict, error). On success error is ''.
    identifier may be an email address or a username.
    """
    identifier = identifier.strip()

    with db_factory() as session:
        if "@" in identifier:
            lookup = User.email == identifier.lower()
        else:
            lookup = User.username == identifier

        user = session.execute(
            select(User).where(lookup)
        ).scalar_one_or_none()

        if not user:
            return None, None, "Invalid credentials"

        if not await verify_password(password, user.hashed_password):
            return None, None, "Invalid credentials"

        if not user.is_verified:
            return None, None, "Please verify your email before logging in"

        if user.is_blocked:
            return None, None, "Account has been blocked"

        if client_ip:
            user.last_ip = _to_ipv4(client_ip)[:45]
            session.commit()
        token = create_jwt(user)
        user_dict = {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "is_verified": user.is_verified,
            "avatar": user.avatar,
            "bio": user.bio,
            "is_admin": user.is_admin,
            "is_blocked": user.is_blocked,
            "bird_notification_email": user.bird_notification_email,
            "auto_join_chat": user.auto_join_chat,
            "profanity_filter_enabled": user.profanity_filter_enabled,
        }
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


def _profile_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "bio": user.bio,
        "avatar": user.avatar,
        "is_admin": user.is_admin,
        "is_blocked": user.is_blocked,
        "bird_notification_email": user.bird_notification_email,
        "auto_join_chat": user.auto_join_chat,
        "profanity_filter_enabled": user.profanity_filter_enabled,
    }


def _set_username(user: User, username: str) -> str:
    """Validates and applies a new username. Returns an error message, or '' on success."""
    username = username.strip()[:50]
    if len(username) < 2:
        return "Username must be at least 2 characters"
    user.username = username
    return ""


def _set_avatar(user: User, avatar: str) -> str:
    """Validates and applies a new avatar. Returns an error message, or '' on success."""
    if avatar and not avatar.startswith("data:image/"):
        return "Invalid image format"
    if len(avatar) > 200_000:
        return "Image too large (max ~150 KB)"
    user.avatar = avatar or None
    return ""


def get_user_profile(db_factory: sessionmaker, user_id: int) -> dict | None:
    with db_factory() as session:
        user = session.get(User, user_id)
        if not user:
            return None
        return _profile_dict(user)


def update_user_profile(
    db_factory: sessionmaker,
    user_id: int,
    email: str | None,
    username: str | None,
    bio: str | None,
    avatar: str | None,
    bird_notification_email: bool | None = None,
    auto_join_chat: bool | None = None,
    profanity_filter_enabled: bool | None = None,
) -> tuple[dict | None, str]:
    """Returns (updated_profile, error). Passes None fields through unchanged."""
    with db_factory() as session:
        user = session.get(User, user_id)
        if not user:
            return None, "User not found"

        if email is not None:
            email = email.lower().strip()
            conflict = session.execute(
                select(User).where(User.email == email, User.id != user_id)
            ).scalar_one_or_none()
            if conflict:
                return None, "Email already in use"
            user.email = email

        if username is not None:
            username = username.strip()[:50]
            if len(username) < 2:
                return None, "Username must be at least 2 characters"
            conflict = session.execute(
                select(User).where(User.username == username, User.id != user_id)
            ).scalar_one_or_none()
            if conflict:
                return None, "Username already taken"
            user.username = username

        if bio is not None:
            user.bio = bio.strip()[:500] or None

        if avatar is not None and (error := _set_avatar(user, avatar)):
            return None, error

        if bird_notification_email is not None:
            user.bird_notification_email = bird_notification_email

        if auto_join_chat is not None:
            user.auto_join_chat = auto_join_chat

        if profanity_filter_enabled is not None:
            user.profanity_filter_enabled = profanity_filter_enabled

        session.commit()
        return _profile_dict(user), ""


def _to_ipv4(ip: str | None) -> str | None:
    if ip and ip.startswith(("::ffff:", "::FFFF:")):
        return ip[7:]
    return ip


def update_last_ip(db_factory: sessionmaker, user_id: int, ip: str | None) -> None:
    ip = _to_ipv4(ip)
    if not ip:
        return
    with db_factory() as session:
        user = session.get(User, user_id)
        if user:
            user.last_ip = ip[:45]
            session.commit()


async def change_user_password(
    db_factory: sessionmaker,
    user_id: int,
    current_password: str,
    new_password: str,
) -> tuple[bool, str]:
    """Returns (success, error)."""
    with db_factory() as session:
        user = session.get(User, user_id)
        if not user:
            return False, "User not found"
        if not await verify_password(current_password, user.hashed_password):
            return False, "Current password is incorrect"
        if len(new_password) < 8:
            return False, "New password must be at least 8 characters"
        user.hashed_password = await hash_password(new_password)
        session.commit()
        return True, ""


async def delete_user_account(
    db_factory: sessionmaker,
    user_id: int,
    current_password: str,
) -> tuple[bool, str]:
    """Permanently delete an account after verifying its current password."""
    with db_factory() as session:
        user = session.get(User, user_id)
        if not user:
            return False, "User not found"
        if not await verify_password(current_password, user.hashed_password):
            return False, "Current password is incorrect"

        session.delete(user)
        session.commit()
        return True, ""


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


def _public_profile(user: User, session, include_profanities: bool) -> dict:
    profile = {"user_id": user.id, "username": user.username, "avatar": user.avatar, "bio": user.bio}
    if include_profanities:
        from services.profanity_service import get_profanity_counts, retention_days
        profile["profanities"] = get_profanity_counts(session, user.id)
        profile["profanity_retention_days"] = retention_days()
        profile["deleted_message_count"] = session.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.user_id == user.id,
                ChatMessage.is_deleted.is_(True),
            )
        ).scalar_one()
    return profile


def get_public_profile_by_username(
    db_factory: sessionmaker, username: str, include_profanities: bool = False
) -> dict | None:
    with db_factory() as session:
        user = session.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()
        if not user:
            return None
        return _public_profile(user, session, include_profanities)


def get_public_profile_by_id(
    db_factory: sessionmaker, user_id: int, include_profanities: bool = False
) -> dict | None:
    with db_factory() as session:
        user = session.get(User, user_id)
        if not user:
            return None
        return _public_profile(user, session, include_profanities)


async def seed_admin_user(
    db_factory: sessionmaker,
    email: str,
    username: str,
    password: str,
) -> None:
    """Create the default admin user if one does not already exist."""
    with db_factory() as session:
        exists = session.execute(
            select(User).where(User.is_admin == True)  # noqa: E712
        ).scalar_one_or_none()
        if exists:
            return

        hashed = await hash_password(password)
        user = User(
            email=email.lower().strip(),
            username=username.strip()[:50],
            hashed_password=hashed,
            is_verified=True,
            is_admin=True,
        )
        session.add(user)
        session.commit()
        logger.info("Default admin user created: %s (%s)", username, email)
