"""CSAT models."""
from __future__ import annotations

import uuid

from django.db import models


class CsatResponse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.OneToOneField(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="csat"
    )
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    invited_at = models.DateTimeField(auto_now_add=True)
    survey_token_hash = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "csat_response"
