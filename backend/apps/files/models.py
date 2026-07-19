"""Models for the Attachments and File Service app."""
from __future__ import annotations

import uuid

from django.db import models


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    object_key = models.CharField(max_length=512)
    checksum_sha256 = models.CharField(max_length=64)
    size_bytes = models.BigIntegerField()
    content_type = models.CharField(max_length=128)
    scan_status = models.CharField(max_length=16, default='pending')

    class Meta:
        db_table = "attachment"

