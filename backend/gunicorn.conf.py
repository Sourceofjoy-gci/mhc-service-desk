"""Gunicorn configuration for the production backend.

Tunings target a small pilot:
  * 2 workers × (2 * cpu + 1) for I/O bound Django
  * graceful_timeout 30 — give in-flight requests time to drain on SIGTERM
  * 60s request timeout — long enough for attachment upload over slow links
  * max-requests jitter to recycle workers and avoid memory leaks
  * access log to stdout, error log to stderr (Docker/k8s friendly)
"""
from __future__ import annotations

import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.environ.get("GUNICORN_WORKERS", str(min(4, (multiprocessing.cpu_count() * 2) + 1))))
worker_class = "sync"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
preload_app = True

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'

proc_name = "mhc-ticketing"
