"""Models for the Administration and Configuration app."""

from __future__ import annotations

import uuid

from django.db import models


class ConfigItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=128, unique=True)
    value = models.JSONField()
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "configitem"

    def __str__(self) -> str:
        return f"config-item:{self.pk}"


class DisposalEvent(models.Model):
    """Committed source of truth for one destructive retention run.

    The filesystem certificate is only a human-readable projection of this
    row.  Keeping the immutable policy/summary and their hashes in PostgreSQL
    makes a failed or delayed export safely retriable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy_snapshot = models.JSONField()
    policy_hash = models.CharField(max_length=64)
    summary = models.JSONField()
    summary_hash = models.CharField(max_length=64)
    certificate_path = models.CharField(max_length=1024)
    created_at = models.DateTimeField(auto_now_add=True)
    object_cleanup_completed_at = models.DateTimeField(null=True, blank=True)
    certificate_exported_at = models.DateTimeField(null=True, blank=True)
    export_error = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "administration_disposal_event"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"disposal-event:{self.pk}"
