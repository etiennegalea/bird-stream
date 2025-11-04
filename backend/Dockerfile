FROM python:3.11-slim-bullseye

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
    python3-opencv \
    && rm -rf /var/lib/apt/lists/*


# Copy only dependency file first (better caching)
COPY requirements.txt .

# Upgrade pip and install Python deps
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy only the application source (this invalidates cache last)
COPY ./src /app
COPY server.py /app

# Expose the API port
EXPOSE 8051

# Start the application
COPY server.py /app/
CMD ["python", "server.py"]
