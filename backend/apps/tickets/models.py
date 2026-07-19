"""Models for the Tickets app."""
from __future__ import annotations

import uuid

from django.db import models


class Ticket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=32, unique=True, db_index=True)
    domain = models.CharField(max_length=16)
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=32)
    priority = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket"

