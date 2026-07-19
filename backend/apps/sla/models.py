"""Models for the SLA and OLA app."""
from __future__ import annotations

import uuid

from django.db import models


class SlaPolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    domain = models.CharField(max_length=16)
    first_response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()

    class Meta:
        db_table = "slapolicy"

