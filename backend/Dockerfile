FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    WEBRTC_PORT_MIN=49152 \
    WEBRTC_PORT_MAX=49251 \
    # Venv lives outside /app so the ./backend:/app bind-mount never overwrites it.
    UV_PROJECT_ENVIRONMENT=/venv

WORKDIR /app

# System deps + non-root user in a single layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg gcc g++ \
    libavdevice-dev libavfilter-dev libopus-dev libvpx-dev libsrtp2-dev \
    libopencv-dev pkg-config python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser

# Install dependencies (separate layer for cache efficiency).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy application source explicitly — keeps secrets (.env, .secrets.yaml)
# and tests out of the image without relying solely on .dockerignore.
COPY controllers/ controllers/
COPY data/ data/
COPY db/ db/
COPY media/ media/
COPY models/ models/
COPY services/ services/
COPY src/ src/
COPY types/ types/
COPY alembic.ini entrypoint.sh main.py server.py ./

ENV PATH="/venv/bin:$PATH"

# Set ownership and make entrypoint executable in one layer.
RUN chmod +x entrypoint.sh \
    && chown -R appuser:appgroup /app /venv

USER appuser

EXPOSE 8051
CMD ["/bin/sh", "entrypoint.sh"]
