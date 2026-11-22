# Tabular Integrity Workbench: one image with the API and the built web interface.
#
#   docker build -t tabular-integrity-workbench .
#   docker run --rm -p 127.0.0.1:8000:8000 -v twb-data:/data tabular-integrity-workbench
#
# Build argument EXTRAS installs optional dependency groups, e.g. --build-arg EXTRAS=postgres
# for the PostgreSQL driver (pg8000). See docs/deployment.md.
#
# Node.js, Python, pip and the Debian release (which fixes the Tesseract version) are the exact
# versions SYSTEM_REQUIREMENTS.md lists (backend/tests/unit/test_system_requirements.py).

# --- 1. The web interface (static files) ---------------------------------------------------
FROM node:24.22.3-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. The runtime --------------------------------------------------------------------------
FROM python:3.13.18-slim-trixie AS runtime
ARG EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Text recognition (OCR) for scanned PDF bills: Tesseract with German and English language
# data (Apache-2.0), run locally by the backend.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 twb \
 && useradd --system --uid 10001 --gid twb --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin twb

WORKDIR /app
# The backend and its dependencies, pinned by the lock file. The package is built from app/,
# so every code change reinstalls them (this layer is not reused).
COPY backend/pyproject.toml backend/requirements.lock.txt backend/README.md ./
COPY backend/app ./app
RUN if [ -n "$EXTRAS" ]; then target=".[$EXTRAS]"; else target="."; fi \
 && python -m pip install pip==26.3 \
 && python -m pip install -c requirements.lock.txt "$target" \
 && rm -rf /root/.cache

COPY --from=frontend /src/frontend/dist /app/frontend
RUN mkdir -p /data && chown twb:twb /data

# The built interface is served at / (TWB_FRONTEND_DIST_DIR); data lives in the /data volume.
# The browser's origin must be allowed for unsafe requests (CSRF origin check); add the
# address users open (and its host to TWB_ALLOWED_HOSTS) when it is not localhost:8000.
ENV TWB_ENVIRONMENT=production \
    TWB_DATA_DIR=/data \
    TWB_FRONTEND_DIST_DIR=/app/frontend \
    TWB_JOBS__AUTO_VALIDATE=true \
    TWB_ALLOWED_HOSTS="[\"localhost\",\"127.0.0.1\"]" \
    TWB_CORS_ORIGINS="[\"http://localhost:8000\",\"http://127.0.0.1:8000\"]"

# The container starts as root only to hand a mounted /data to twb; the server runs as twb.
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4); sys.exit(0 if r.status == 200 else 1)"]

# One process: background runs and their start-up recovery assume one worker per database.
# --no-access-log: the application writes its own access line (with the request id), so
# uvicorn's would only repeat it.
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
