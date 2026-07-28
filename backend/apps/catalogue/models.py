"""Service catalogue, request types, custom fields and forms.

Everything in this app is configuration, not business data. Administrators
can change it without code changes (PRD FR-089).
"""
from __future__ import annotations

import uuid

from django.db import models


class Service(models.Model):
    """A service offered by the Master's Office (e.g. Will registration)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    domain = models.CharField(max_length=16, choices=[("operational", "Operational"), ("it", "IT")])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalogue_service"
        ordering = ("name",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code} — {self.name}"


class RequestType(models.Model):
    """A kind of request within a service (e.g. 'New will registration')."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="request_types")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    default_priority = models.CharField(max_length=8, default="P3")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "catalogue_request_type"
        unique_together = [("service", "code")]

    def __str__(self) -> str:
        return f"request-type:{self.pk}"


class CustomFieldDefinition(models.Model):
    """A field that a request type collects beyond the common ones."""

    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        TEXTAREA = "textarea", "Textarea"
        SELECT = "select", "Select"
        MULTISELECT = "multiselect", "Multiselect"
        DATE = "date", "Date"
        NUMBER = "number", "Number"
        BOOLEAN = "boolean", "Boolean"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_type = models.ForeignKey(
        RequestType, on_delete=models.CASCADE, related_name="fields"
    )
    key = models.CharField(max_length=64)
    label = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    required = models.BooleanField(default=False)
    choices = models.JSONField(default=list, blank=True)
    help_text = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "catalogue_custom_field"
        unique_together = [("request_type", "key")]
        ordering = ("order", "key")

    def __str__(self) -> str:
        return f"custom-field:{self.pk}"
