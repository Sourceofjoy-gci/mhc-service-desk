"""Durable retention side effects: exact object deletion and certificate export."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from botocore.exceptions import ClientError
from celery import Task, shared_task
from django.db import transaction
from django.utils import timezone

from apps.files.models import ObjectDeleteJob
from apps.files.services import StoredObject, delete_from_minio

from .models import DisposalEvent
from .retention import Command

logger = logging.getLogger(__name__)


def _is_idempotent_missing(exc: BaseException) -> bool:
    if not isinstance(exc, ClientError):
        return False
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code in {"NoSuchKey", "NoSuchVersion"}


def _process_one_due_job() -> tuple[bool, bool] | None:
    with transaction.atomic():
        job = (
            ObjectDeleteJob.objects.select_for_update(skip_locked=True)
            .filter(completed_at__isnull=True, next_attempt_at__lte=timezone.now())
            .order_by("next_attempt_at", "created_at")
            .first()
        )
        if job is None:
            return None
        stored_object = StoredObject(
            bucket=job.bucket,
            key=job.object_key,
            etag=job.etag,
            version_id=job.version_id,
        )
        try:
            delete_from_minio(stored_object=stored_object)
        except Exception as exc:
            if not _is_idempotent_missing(exc):
                job.attempts += 1
                delay = min(3600, 2 ** min(job.attempts, 11))
                job.next_attempt_at = timezone.now() + timedelta(seconds=delay)
                job.last_error_code = type(exc).__name__[:128]
                job.save(
                    update_fields=(
                        "attempts",
                        "next_attempt_at",
                        "last_error_code",
                    )
                )
                return False, True
        job.completed_at = timezone.now()
        job.last_error_code = ""
        job.save(update_fields=("completed_at", "last_error_code"))
        event = DisposalEvent.objects.select_for_update().get(pk=job.disposal_event_id)
        if not event.object_delete_jobs.filter(completed_at__isnull=True).exists():
            event.object_cleanup_completed_at = timezone.now()
            event.save(update_fields=("object_cleanup_completed_at",))
        return True, False


def _process_retention_side_effects() -> dict[str, int]:
    completed = 0
    failed = 0
    while True:
        result = _process_one_due_job()
        if result is None:
            break
        completed += int(result[0])
        failed += int(result[1])

    published = 0
    pending_exports = DisposalEvent.objects.filter(
        object_cleanup_completed_at__isnull=False,
        certificate_exported_at__isnull=True,
    ).order_by("created_at")
    for event in pending_exports:
        try:
            Command()._export_disposal_event(event)
        except Exception:
            logger.exception(
                "retention_certificate_export_failed",
                extra={"disposal_event_id": str(event.pk)},
            )
        else:
            published += 1
    return {"completed": completed, "failed": failed, "published": published}


_register_process_retention: Callable[[Callable[[], dict[str, int]]], Task] = shared_task(
    name="apps.administration.tasks.process_retention_side_effects"
)
process_retention_side_effects = _register_process_retention(_process_retention_side_effects)
