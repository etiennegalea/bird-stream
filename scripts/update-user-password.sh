#!/bin/sh
set -eu

usage() {
    echo "Usage: $0 <username>" >&2
    echo "Prompts securely for a new Bird Stream password." >&2
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    usage
    exit 0
fi

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

username=$1

restore_echo() {
    stty echo < /dev/tty 2>/dev/null || true
}

trap restore_echo 0 1 2 15
printf "New password for '%s': " "$username" > /dev/tty
stty -echo < /dev/tty
IFS= read -r password < /dev/tty
printf '\nConfirm new password: ' > /dev/tty
IFS= read -r confirmation < /dev/tty
restore_echo
trap - 0 1 2 15
printf '\n' > /dev/tty

if [ "${#password}" -lt 8 ]; then
    echo "Password must be at least 8 characters." >&2
    exit 2
fi
if [ "$password" != "$confirmation" ]; then
    echo "Passwords do not match." >&2
    exit 2
fi

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
project_dir=$(dirname "$script_dir")

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
