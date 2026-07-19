"""Contact directory — requesters, practitioners, organisations.

Stores identity data captured from any intake channel. Sensitive identifiers
are masked at the API boundary; raw values are restricted to authorised roles
(PRD §23.1).
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class Contact(models.Model):
    """A person who can request or be referenced on a ticket."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, db_index=True)
    phone_e164 = models.CharField(max_length=32, blank=True, db_index=True)
    national_id_hash = models.CharField(max_length=64, blank=True, db_index=True)
    language = models.CharField(max_length=8, default="en")
    consent_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    opted_out_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "contact"
        indexes = [
            models.Index(fields=["full_name"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["email"],
                condition=~models.Q(email=""),
                name="uniq_contact_email_when_set",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return self.full_name

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None


class Organisation(models.Model):
    """A firm, chamber, court or other entity that may be a requester."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, db_index=True)
    contact = models.ForeignKey(
        Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name="organisations"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contact_organisation"

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class ContactMethod(models.Model):
    """Multiple ways to reach a contact. Replaces scattered fields on demand."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="methods")
    method = models.CharField(max_length=16)  # email, phone, whatsapp, sms, postal
    value = models.CharField(max_length=255)
    is_primary = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "contact_method"
        unique_together = [("contact", "method", "value")]


class VerificationToken(models.Model):
    """Magic link / one-time code sent to a contact for status access (FR-071)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="tokens")
    token_hash = models.CharField(max_length=128, unique=True, db_index=True)
    purpose = models.CharField(max_length=32, default="status")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contact_verification_token"
        indexes = [models.Index(fields=["expires_at"])]

    def is_valid(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()
