# syntax=docker/dockerfile:1.7
# =============================================================================
# MHC e-Ticketing — backend image
# Used by web, worker, and beat services.
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System dependencies: build tools, libpq, libmagic, clamav client libs, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libmagic1 \
        libclamav-dev \
        clamav-daemon \
        clamav-freshclam \
        curl \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies separately to leverage Docker layer cache
COPY requirements/ ./requirements/
RUN pip install --upgrade pip && \
    pip install -r requirements/base.txt

# Copy application source
COPY . /app

# Drop privileges
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 8000

# Default command (overridden by docker-compose for worker/beat)
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
