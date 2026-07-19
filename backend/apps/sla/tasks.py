"""SLA background tasks.

The periodic evaluator reads persisted SLA instances from PostgreSQL,
computes remaining time against the business calendar, and dispatches
notifications or escalations. SLA timers are never held in queue memory.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.sla.tasks.evaluate_open_slas")
def evaluate_open_slas() -> int:
    """Sweep all open SLA instances once per minute.

    Implementation deferred to Milestone 2 (Operational Vertical Slice).
    This stub keeps the beat schedule valid from day one.
    """
    logger.debug("sla_evaluator_tick")
    return 0
