"""Background tasks for the audit app.

Currently a placeholder for periodic export rotation; will be expanded
when retention and disposal rules are finalised.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.audit.tasks.rotate_export_artefacts")
def rotate_export_artefacts() -> int:
    """Delete expired CSV / XLSX export files from object storage."""
    logger.info("audit_export_rotation_started")
    # Implementation deferred until P1 export scheduling lands (FR-088)
    return 0
