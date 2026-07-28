"""WhatsApp channel models."""
from __future__ import annotations

import uuid

from django.db import models


class WhatsappAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number_id = models.CharField(max_length=64, unique=True)
    business_id = models.CharField(max_length=128, blank=True)
    display_name = models.CharField(max_length=128)
    domain = models.CharField(max_length=16, choices=[("operational", "Operational"), ("it", "IT")])
    is_active = models.BooleanField(default=True)
    access_token = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "whatsapp_account"

    def __str__(self) -> str:
        return f"whatsapp-account:{self.pk}"


class WhatsappMessage(models.Model):
    """Audit log of every inbound/outbound WhatsApp message we touch."""

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_messages",
    )
    account = models.ForeignKey(
        WhatsappAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    from_number = models.CharField(max_length=32, blank=True)
    to_number = models.CharField(max_length=32, blank=True)
    direction = models.CharField(max_length=16, choices=Direction.choices)
    body = models.TextField()
    external_message_id = models.CharField(max_length=128, blank=True, db_index=True)
    delivery_status = models.CharField(max_length=32, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "whatsapp_message"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("external_message_id",),
                condition=~models.Q(external_message_id=""),
                name="uniq_whatsapp_external_message_when_set",
            )
        ]

    def __str__(self) -> str:
        return f"whatsapp-message:{self.pk}"
