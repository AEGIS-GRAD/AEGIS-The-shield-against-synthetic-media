FROM python:3.11-slim

WORKDIR /app

# System deps:
#   curl   – used by the docker-compose healthcheck (curl -f http://localhost:8000/health)
#   sqlite3 – CLI access to the decision log for debugging
#   ffmpeg  – provides ffprobe, which metadata.py uses to detect modality/audio/resolution
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire orchestrator directory into /app.
# This places app/ at /app/app/, so the uvicorn module path is app.main:app.
COPY . /app

# Set the working directory to the inner app folder where main.py lives
WORKDIR /app/app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]