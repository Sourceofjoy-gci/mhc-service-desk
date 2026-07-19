"""Celery application factory for the MHC e-Ticketing platform.

Tasks are discovered from every installed app. Long-running or external work
must go through Celery — never block a request thread.
"""
from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("mhc")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):  # pragma: no cover - debug aid
    print(f"Request: {self.request!r}")
