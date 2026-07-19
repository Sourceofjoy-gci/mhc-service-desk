"""Attachments — file metadata, scan results and access grants.

The bytes live in MinIO. Short-lived signed URLs are issued on demand
(FR-095). ClamAV scan results are recorded before any download.
"""
from __future__ import annotations

import uuid

from django.db import models


class Attachment(models.Model):
    """Metadata about a file linked to a ticket or message."""

    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CLEAN = "clean", "Clean"
        INFECTED = "infected", "Infected"
        ERROR = "error", "Scan error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="attachments"
    )
    message = models.ForeignKey(
        "tickets.TicketMessage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attachments",
    )
    object_key = models.CharField(max_length=512, unique=True)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size_bytes = models.BigIntegerField()
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    scan_status = models.CharField(
        max_length=16, choices=ScanStatus.choices, default=ScanStatus.PENDING
    )
    scan_signature = models.CharField(max_length=128, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    quarantine_path = models.CharField(max_length=512, blank=True)
    uploaded_by_subject = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "file_attachment"
        ordering = ("-uploaded_at",)
        indexes = [
            models.Index(fields=["ticket", "-uploaded_at"]),
        ]


class AttachmentAccessLog(models.Model):
    """Every download is audited (FR-095, FR-097)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attachment = models.ForeignKey(
        Attachment, on_delete=models.CASCADE, related_name="access_log"
    )
    actor_subject = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.CharField(max_length=512, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "file_attachment_access"
        ordering = ("-at",)
