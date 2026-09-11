FROM python:3.10-slim

WORKDIR /app

# Install system dependencies required for OpenCV, video decoding, and network healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install CPU PyTorch & Torchvision
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu

# Install application requirements
COPY requirements.txt .
RUN grep -v "^torch" requirements.txt > /tmp/reqs.txt && \
    pip install --no-cache-dir -r /tmp/reqs.txt && \
    rm /tmp/reqs.txt

# Create models volume directory for future checkpoint storage
RUN mkdir -p /app/models

# Copy microservice source code
COPY . /app

EXPOSE 8000

# Run microservice using Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
