# Lightweight multi-stage image for Raspberry Pi 5 (ARM64) and amd64.
# HTTP crawling only — never install Playwright/Chromium browser binaries.
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir .

# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    WORKER_HEARTBEAT_PATH=/tmp/collector_heartbeat

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 collector \
    && useradd --system --uid 1000 --gid collector --home-dir /app --shell /usr/sbin/nologin collector

COPY --from=builder /opt/venv /opt/venv
COPY migrations ./migrations
COPY config ./config
COPY app ./app
COPY pyproject.toml README.md ./

# Do NOT run `scrapling install` / `playwright install` — no browsers.
USER collector

HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
    CMD python -m app.cli health --max-heartbeat-age 600

CMD ["python", "-m", "app.cli", "worker"]
