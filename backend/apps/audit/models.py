"""Models for the Audit app."""
from __future__ import annotations

import uuid

from django.db import models


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_subject = models.CharField(max_length=255, db_index=True)
    action = models.CharField(max_length=128)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    ip_address = models.GenericIPAddressField(null=True)
    payload = models.JSONField(default=dict, blank=True)
    payload_hash = models.CharField(max_length=64)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "auditevent"

