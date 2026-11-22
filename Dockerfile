# syntax=docker/dockerfile:1.7
# One container: FastAPI serves the API and the built phone app on the same origin.

# --- 1. build the phone app ---------------------------------------------------------
FROM node:22.12-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Python runtime ---------------------------------------------------------------
FROM python:3.12-slim-bookworm AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app/backend
# Dependencies first (cached unless the lock file changes); no dev tools in the image.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY backend/scripts/start.sh ./scripts/start.sh
COPY --from=web /src/frontend/dist /app/frontend/dist

RUN useradd --system --uid 10001 --home /app app \
    && mkdir -p /app/backend/data \
    && chown -R app /app/backend/data
USER app

ENV PATH="/app/backend/.venv/bin:$PATH" \
    FRONTEND_DIST=/app/frontend/dist \
    PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=4)"
CMD ["sh", "scripts/start.sh"]
