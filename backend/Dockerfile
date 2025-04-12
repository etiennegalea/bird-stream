# Use the official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV WEBRTC_PORT_MIN=49152
ENV WEBRTC_PORT_MAX=49251

# Set working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl\
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

# Copy the application files
COPY ./src /app
COPY requirements.txt /tmp/

# Upgrade pip
RUN pip install --upgrade pip

# Install requirements from tmp dir
RUN pip install --requirement /tmp/requirements.txt

COPY . /tmp/

# Expose the API port
EXPOSE 8051

# Start the application
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8051"]
