"""Models for the Integrations app."""

from __future__ import annotations

import uuid

from django.db import models


class IntegrationEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32)
    external_id = models.CharField(max_length=255, db_index=True)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integrationevent"

    def __str__(self) -> str:
        return f"integration-event:{self.pk}"
