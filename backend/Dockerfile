# Use the official Python image
FROM python:3.11-slim

# Install required system packages for OpenCV
RUN apt-get update && apt-get install -y libopencv-dev python3-opencv && rm -rf /var/lib/apt/lists/*

# Set working directory in the container
WORKDIR /app

# Copy the application files
COPY src/ /app/
COPY requirements.txt /app/

# Install dependencies
RUN pip install -r requirements.txt --no-cache-dir asyncio fastapi opencv-python-headless uvicorn

# Expose the port
EXPOSE 2096

# Start the application
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "2096"]
