"""Models for the Contacts and Directory app."""
from __future__ import annotations

import uuid

from django.db import models


class Contact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone_e164 = models.CharField(max_length=32, blank=True, db_index=True)
    language = models.CharField(max_length=8, default='en')
    consent_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "contact"

