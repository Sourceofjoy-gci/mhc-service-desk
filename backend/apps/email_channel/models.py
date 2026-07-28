"""Models for the email channel — mailboxes, message log."""
from __future__ import annotations

import uuid

from django.db import models


class Mailbox(models.Model):
    """A configured inbound mailbox (e.g. operations@mhc.gov.sz)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    address = models.EmailField(unique=True)
    domain = models.CharField(max_length=16, choices=[("operational", "Operational"), ("it", "IT")])
    is_active = models.BooleanField(default=True)
    # Supported values: graph, mailgun, sendgrid, generic.
    provider = models.CharField(max_length=32, default="generic")
    secret = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "email_mailbox"
        ordering = ("address",)

    def __str__(self) -> str:
        return f"mailbox:{self.pk}"


class EmailDelivery(models.Model):
    """An outbound email attempt and its result."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        BOUNCED = "bounced", "Bounced"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket_message = models.ForeignKey(
        "tickets.TicketMessage", on_delete=models.CASCADE, related_name="email_deliveries"
    )
    to_address = models.EmailField()
    from_address = models.EmailField()
    subject = models.CharField(max_length=512)
    body_text = models.TextField()
    message_id = models.CharField(max_length=255, blank=True, db_index=True)
    in_reply_to = models.CharField(max_length=255, blank=True)
    references = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "email_delivery"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"email-delivery:{self.pk}"
