"""Models for the Service Catalogue and Request Types app."""
from __future__ import annotations

import uuid

from django.db import models


class Service(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=16)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "service"

