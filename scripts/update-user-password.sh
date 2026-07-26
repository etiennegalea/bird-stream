#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <username>" >&2
    exit 2
fi

username=$1

read -r -s -p "New password for '$username': " password
echo
read -r -s -p "Confirm new password: " confirmation
echo

if [[ ${#password} -lt 8 ]]; then
    echo "Password must be at least 8 characters." >&2
    exit 2
fi
if [[ $password != "$confirmation" ]]; then
    echo "Passwords do not match." >&2
    exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(dirname -- "$script_dir")

printf %s "$password" | docker compose --project-directory "$project_dir" exec -T backend \
    python -c '
import asyncio
import sys

from sqlalchemy import select

from db.session import SessionLocal
from models.orm import User
from services.auth_service import hash_password

async def update_password():
    username = sys.argv[1]
    password = sys.stdin.read()
    with SessionLocal() as session:
        user = session.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()
        if user is None:
            print(f"User {username!r} does not exist.", file=sys.stderr)
            return 1
        user.hashed_password = await hash_password(password)
        session.commit()
    print(f"Password updated for {username!r}.")
    return 0

raise SystemExit(asyncio.run(update_password()))
' "$username"

unset password confirmation
