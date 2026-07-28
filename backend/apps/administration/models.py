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

