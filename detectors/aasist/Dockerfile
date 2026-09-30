FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for audio decoding and network downloads
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install CPU PyTorch
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch torchaudio --extra-index-url https://download.pytorch.org/whl/cpu

# Install application dependencies
COPY requirements.txt .
# Filter out torch/torchaudio from requirements if already installed
RUN grep -v "^torch" requirements.txt > /tmp/reqs.txt && \
    pip install --no-cache-dir -r /tmp/reqs.txt && \
    rm /tmp/reqs.txt

# AASIST.pth lives at the detector root and is brought in by "COPY . /app" below.
# No network download needed.

# Copy application source
COPY . /app

EXPOSE 8000

# Run microservice with Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
