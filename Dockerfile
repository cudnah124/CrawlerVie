FROM python:3.12-slim-bookworm

# ── Build args ─────────────────────────────────────────────────────────────────
ARG APP_HOME=/app
ARG CRAWLERAI_VERSION=0.1.0
ENV CRAWLERAI_VERSION=$CRAWLERAI_VERSION

# ── Python env ─────────────────────────────────────────────────────────────────
ENV PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    DEBIAN_FRONTEND=noninteractive

LABEL maintainer="crawlerai"
LABEL description="crawlerai — Lightweight web crawler with LLM and CSS schema extraction"
LABEL version=$CRAWLERAI_VERSION

# ── System deps (Playwright Chromium requirements) ─────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    git \
    build-essential \
    # Chromium system libs
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ──────────────────────────────────────────────────────────────
RUN groupadd -r appuser && useradd --no-log-init -r -g appuser appuser \
    && mkdir -p /home/appuser && chown -R appuser:appuser /home/appuser

WORKDIR ${APP_HOME}

# ── Install Python package ─────────────────────────────────────────────────────
COPY . /tmp/crawlerai/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "/tmp/crawlerai[cli]" \
    && python -c "import crawlerai; print('✅ crawlerai installed:', crawlerai.__version__)"

# ── Install Playwright browser (headless Chromium) ────────────────────────────
RUN playwright install chromium --with-deps \
    && mkdir -p /home/appuser/.cache/ms-playwright \
    && cp -r /root/.cache/ms-playwright/chromium-* /home/appuser/.cache/ms-playwright/ \
    && chown -R appuser:appuser /home/appuser/.cache/ms-playwright

# Note: NhaTot scraper requires headless=False (visible browser) and cannot
# run in a headless Docker container. Use the library programmatically in
# environments with a display, or via Xvfb in the container.

RUN chown -R appuser:appuser ${APP_HOME}

# ── Health check ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import crawlerai; print('ok')" || exit 1

EXPOSE 8000

USER appuser

# Default: start an interactive Python shell.
# Override CMD in docker-compose or docker run to run your script.
CMD ["python", "-c", "import crawlerai; print('crawlerai', crawlerai.__version__, 'ready.')"]
