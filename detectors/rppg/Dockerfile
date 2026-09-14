FROM python:3.10-slim

WORKDIR /app

# System dependencies: libgl1/libglib2.0-0 required by OpenCV,
# ffmpeg for video decoding, curl for healthcheck probe.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (needed by facenet-pytorch / MTCNN).
# Separated from requirements.txt so the layer is cached independently.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch torchvision \
        --extra-index-url https://download.pytorch.org/whl/cpu

# Install remaining application requirements (excludes torch line).
COPY requirements.txt .
RUN grep -v "^torch" requirements.txt > /tmp/reqs.txt && \
    pip install --no-cache-dir -r /tmp/reqs.txt && \
    rm /tmp/reqs.txt

# Copy microservice source code.
# No model weights directory needed — this is a pure signal-processing detector.
COPY . /app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
