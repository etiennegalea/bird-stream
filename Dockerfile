# Use a lightweight Python image
FROM python:3.11-slim

# Install required packages
RUN apt-get update && apt-get install -y libopencv-dev python3-opencv && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY app.py /app/

# Install Python dependencies
RUN pip install fastapi uvicorn

# Expose the streaming port
EXPOSE 8050

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8050"]
