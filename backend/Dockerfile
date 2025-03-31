# Use the official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

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

# Set working directory in the container
WORKDIR /app

# Copy the application files
COPY src/ /app/
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install -r requirements.txt

# Expose the port
EXPOSE 2096

# Start the application
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "2096"]
