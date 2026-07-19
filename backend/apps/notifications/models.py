"""Models for the Notifications app."""
from __future__ import annotations

import uuid

from django.db import models


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.CharField(max_length=16)
    recipient = models.CharField(max_length=255)
    template_key = models.CharField(max_length=128)
    payload = models.JSONField()
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification"

