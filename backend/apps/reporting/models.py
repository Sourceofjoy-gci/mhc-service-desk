"""Models for the Reporting and Dashboards app."""
from __future__ import annotations

import uuid

from django.db import models


class Dashboard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=255)
    domain = models.CharField(max_length=16)

    class Meta:
        db_table = "dashboard"

    def __str__(self) -> str:
        return self.title

