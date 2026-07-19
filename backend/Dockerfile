# syntax=docker/dockerfile:1.7
# =============================================================================
# MHC e-Ticketing — production backend image
# Runs gunicorn with the prod settings. The dev profile uses Dockerfile.dev.
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        libmagic1 \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements/ ./requirements/
RUN pip install --upgrade pip && \
    pip install -r requirements/base.txt && \
    pip install gunicorn==23.0.0

COPY . /app

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

ENV DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/api/v1/health/live || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "config.wsgi:application"]
