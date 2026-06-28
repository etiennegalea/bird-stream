# Use the official Python image
FROM python:3.12-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV WEBRTC_PORT_MIN=49152
ENV WEBRTC_PORT_MAX=49251

# Set working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    gcc \
    g++ \
    libavdevice-dev \
    libavfilter-dev \
    libopus-dev \
    libvpx-dev \
    libsrtp2-dev \
    libopencv-dev \
    pkg-config \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition files first (leverage Docker build cache)
COPY pyproject.toml uv.lock ./

# Install dependencies using uv sync (creates a virtual environment in /app/.venv)
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application files
COPY . .

# Add the virtual environment to PATH so the application runs within it
ENV PATH="/app/.venv/bin:$PATH"

# Expose the API port
EXPOSE 8051

# Start the application
CMD ["python", "server.py"]
