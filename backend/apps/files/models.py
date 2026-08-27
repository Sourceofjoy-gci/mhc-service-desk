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
    # Exact ownership coordinates returned by a versioned object-store write.
    # Blank values identify legacy rows and retention must preserve them.
    object_bucket = models.CharField(max_length=255, blank=True)
    object_version_id = models.CharField(max_length=255, blank=True)
    object_etag = models.CharField(max_length=255, blank=True)
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

    def __str__(self) -> str:
        return f"attachment:{self.pk}"


class AttachmentAccessLog(models.Model):
    """Every download is audited (FR-095, FR-097)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attachment = models.ForeignKey(Attachment, on_delete=models.CASCADE, related_name="access_log")
    actor_subject = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.CharField(max_length=512, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "file_attachment_access"
        ordering = ("-at",)

    def __str__(self) -> str:
        return f"attachment-access:{self.pk}"


class ObjectDeleteJob(models.Model):
    """Durable request to remove one exact object-store version."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    disposal_event = models.ForeignKey(
        "administration.DisposalEvent",
        on_delete=models.PROTECT,
        related_name="object_delete_jobs",
    )
    source_attachment_id = models.UUIDField()
    bucket = models.CharField(max_length=255)
    object_key = models.CharField(max_length=512)
    version_id = models.CharField(max_length=255)
    etag = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    last_error_code = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "file_object_delete_job"
        constraints = [
            models.UniqueConstraint(
                fields=("bucket", "object_key", "version_id"),
                name="uniq_object_delete_exact_version",
            )
        ]
        indexes = [models.Index(fields=("completed_at", "next_attempt_at"))]

    def __str__(self) -> str:
        return f"object-delete-job:{self.pk}"
