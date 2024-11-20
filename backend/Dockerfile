# Use the official Python image
FROM python:3.11-slim

# Install required system packages for OpenCV
RUN apt-get update && apt-get install -y libopencv-dev python3-opencv && rm -rf /var/lib/apt/lists/*

# Set working directory in the container
WORKDIR /app

# Copy the application files
COPY src/app.py /app/
COPY requirements.txt /app/

# Install dependencies
RUN pip install -r requirements.txt
RUN pip install --no-cache-dir fastapi uvicorn opencv-python-headless asyncio

# Expose the port
EXPOSE 8051

# Start the application
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8051"]
