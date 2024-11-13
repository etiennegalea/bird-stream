# Use a lightweight Python image
FROM python:3.11-slim

# Install required system packages for OpenCV
RUN apt-get update && apt-get install -y libopencv-dev python3-opencv && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the application files
COPY app.py /app/
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the streaming port
EXPOSE 8051

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8051"]
