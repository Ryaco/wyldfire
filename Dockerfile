# Multi-arch lightweight container for Wyldfire Sync Server
# Supports linux/amd64 (VPS/cloud) and linux/arm64 (Raspberry Pi)

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WYLD_DATA_DIR=/data \
    PORT=8000

# Install dependencies and wyldfire package
WORKDIR /app

# Copy package files
COPY pyproject.toml README.md ./
COPY wyldfire ./wyldfire

# Install wyldfire with server dependencies
RUN pip install --no-cache-dir ".[server]"

# Create data directory for persistent SQLite database
RUN mkdir -p /data

VOLUME ["/data"]

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

# Default command
CMD ["sh", "-c", "uvicorn wyldfire.server.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
