FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    WEBRTC_PORT_MIN=49152 \
    WEBRTC_PORT_MAX=49251 \
    XDG_CACHE_HOME=/var/cache/birdstream \
    MPLCONFIGDIR=/var/cache/birdstream/matplotlib \
    YOLO_CONFIG_DIR=/var/cache/birdstream/ultralytics \
    # Keep uv's build cache on the BuildKit cache mount instead of baking it
    # into XDG_CACHE_HOME. Copies avoid hardlinks into the ephemeral mount.
    UV_CACHE_DIR=/root/.cache/uv \
    UV_LINK_MODE=copy \
    # Venv lives outside /app so the ./backend:/app bind-mount never overwrites it.
    UV_PROJECT_ENVIRONMENT=/venv

WORKDIR /app

# Native dependencies (AV, OpenCV, SRTP, crypto) are provided by locked
# manylinux wheels, so no compiler, FFmpeg SDK, or second Python toolchain is
# needed in the runtime image.
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser

# Install dependencies (separate layer for cache efficiency).
# INSTALL_DETECTION=true also installs the optional bird-detection group
# (ultralytics + torch CPU, big layer) used when DETECTION_ENABLED=true.
ARG INSTALL_DETECTION=false
COPY pyproject.toml uv.lock ./
# Cache mount: package downloads survive across builds (BuildKit).
# Ultralytics depends on the GUI OpenCV distribution. Both OpenCV wheels own
# the same `cv2` package, so whichever installs last wins; in the slim runtime
# that GUI build crashes looking for libxcb. Detection builds therefore remove
# it, restore the locked headless wheel, and verify that cv2 imports.
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_DETECTION" = "true" ]; then \
        uv sync --frozen --no-install-project --no-dev --group detection \
        && uv pip uninstall --python /venv/bin/python opencv-python \
        && uv pip install --python /venv/bin/python --reinstall --no-deps \
            opencv-python-headless==5.0.0.93 \
        && /venv/bin/python -c "import cv2; print('headless cv2', cv2.__version__)"; \
    else \
        uv sync --frozen --no-install-project --no-dev; \
    fi

# Copy application source explicitly — keeps secrets (.env, .secrets.yaml)
# and tests out of the image without relying solely on .dockerignore.
COPY controllers/ controllers/
COPY db/ db/
COPY media/ media/
COPY models/ models/
COPY scripts/ scripts/
COPY services/ services/
COPY src/ src/
COPY alembic.ini entrypoint.sh main.py server.py ./

ENV PATH="/venv/bin:$PATH"

# Set ownership and make entrypoint executable in one layer.
RUN chmod +x entrypoint.sh \
    && mkdir -p /var/lib/birdstream/models \
        /var/cache/birdstream/matplotlib \
        /var/cache/birdstream/ultralytics \
    && chown -R appuser:appgroup /app /venv /var/lib/birdstream \
        /var/cache/birdstream

USER appuser

EXPOSE 8051
CMD ["/bin/sh", "entrypoint.sh"]
