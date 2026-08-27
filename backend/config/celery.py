"""Celery application factory for the MHC e-Ticketing platform.

Tasks are discovered from every installed app. Long-running or external work
must go through Celery — never block a request thread.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from celery import Celery, Task

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("mhc")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


def _debug_task(self: Task) -> None:  # pragma: no cover - debug aid
    print(f"Request: {self.request!r}")


_register_debug_task: Callable[[Callable[[Task], None]], Task] = app.task(
    bind=True,
    ignore_result=True,
    name="config.celery.debug_task",
)
debug_task = _register_debug_task(_debug_task)
