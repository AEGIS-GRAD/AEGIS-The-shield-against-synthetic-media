FROM python:3.11.18-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get upgrade -y --no-install-recommends && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==26.3 setuptools==84.2.1 wheel==0.48.0 \
    && rm -rf /usr/local/lib/python3.*/ensurepip \
    && find /usr -path "*/pip/_vendor/bom.cdx.json" -delete \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser bridge.py /app/bridge.py
RUN chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import pathlib; assert 'bridge.py' in pathlib.Path('/proc/1/cmdline').read_text()" || exit 1

CMD ["python", "-u", "/app/bridge.py"]
