"""Background tasks for the audit app.

Currently a placeholder for periodic export rotation; will be expanded
when retention and disposal rules are finalised.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from celery import Task, shared_task

logger = logging.getLogger(__name__)


def _rotate_export_artefacts() -> int:
    """Delete expired CSV / XLSX export files from object storage."""
    logger.info("audit_export_rotation_started")
    # Implementation deferred until P1 export scheduling lands (FR-088)
    return 0


_register_rotate_export: Callable[[Callable[[], int]], Task] = shared_task(
    name="apps.audit.tasks.rotate_export_artefacts"
)
rotate_export_artefacts = _register_rotate_export(_rotate_export_artefacts)
