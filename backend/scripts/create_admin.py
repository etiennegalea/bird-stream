#!/usr/bin/env python3
"""Create (or promote) an admin user.

Usage:
    python scripts/create_admin.py admin:somepassword
    python scripts/create_admin.py admin:somepassword --email admin@birb.local

    # inside the running container:
    docker exec stream-backend python scripts/create_admin.py admin:somepassword

    # locally against the compose DB:
    cd backend && uv run python scripts/create_admin.py admin:somepassword

Behavior:
- No user with that username -> created as verified admin.
- User exists -> promoted to admin; password is updated only with --update-password.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as `python scripts/create_admin.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
except ImportError:  # not installed in the container image; env comes from compose
    def load_dotenv(*_a, **_k):
        return None

_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_backend_dir.parent / ".env")

from sqlalchemy import select  # noqa: E402

from db.session import SessionLocal  # noqa: E402
from models.orm import User  # noqa: E402
from services.auth_service import hash_password  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Create or promote an admin user")
    parser.add_argument("credentials", help="USERNAME:PASSWORD (e.g. admin:somepassword)")
    parser.add_argument("--email", default=None,
                        help="Email for a newly created user (default: <username>@birb.local)")
    parser.add_argument("--update-password", action="store_true",
                        help="Also reset the password if the user already exists")
    args = parser.parse_args()

    if ":" not in args.credentials:
        parser.error("credentials must be USERNAME:PASSWORD")
    username, password = args.credentials.split(":", 1)
    username = username.strip()[:50]
    if not username or not password:
        parser.error("username and password must be non-empty")

    email = (args.email or f"{username}@birb.local").lower().strip()

    with SessionLocal() as session:
        user = session.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()

        if user:
            changes = []
            if not user.is_admin:
                user.is_admin = True
                changes.append("promoted to admin")
            if not user.is_verified:
                user.is_verified = True
                changes.append("marked verified")
            if args.update_password:
                user.hashed_password = await hash_password(password)
                changes.append("password updated")
            if changes:
                session.commit()
                print(f"User '{username}': {', '.join(changes)}.")
            else:
                print(f"User '{username}' is already a verified admin. "
                      "(use --update-password to reset the password)")
            return 0

        # email must be unique too
        email_taken = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if email_taken:
            print(f"Error: email '{email}' already belongs to user "
                  f"'{email_taken.username}'. Pass --email to choose another.")
            return 1

        session.add(User(
            email=email,
            username=username,
            hashed_password=await hash_password(password),
            is_verified=True,
            is_admin=True,
        ))
        session.commit()
        print(f"Admin user '{username}' created ({email}).")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
