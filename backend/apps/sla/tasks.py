"""SLA background tasks.

The periodic evaluator reads persisted SLA instances from PostgreSQL,
computes remaining time against the business calendar, and dispatches
notifications or escalations. SLA timers are never held in queue memory.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from celery import Task, shared_task

from .services import evaluate_open_slas

logger = logging.getLogger(__name__)


def _evaluate_open_slas_task() -> int:
    """Sweep all open SLA instances once per minute."""
    return evaluate_open_slas()


_register_evaluate_slas: Callable[[Callable[[], int]], Task] = shared_task(
    name="apps.sla.tasks.evaluate_open_slas"
)
evaluate_open_slas_task = _register_evaluate_slas(_evaluate_open_slas_task)
