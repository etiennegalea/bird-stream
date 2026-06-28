#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
exec python server.py
