"""Geographic and organisational structure.

Models in this app establish the boundaries for authorisation, reporting and
SLA calendars. The Office is the lowest level used in scope checks; a Queue
hierarchy can be introduced later.
"""

from __future__ import annotations

import uuid

from django.db import models


class Region(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "org_region"
        ordering = ("name",)

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Office(models.Model):
    """A physical or virtual office of the Master's Office."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="offices")
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    timezone = models.CharField(max_length=64, default="Africa/Mbabane")
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "org_office"
        ordering = ("name",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.code} — {self.name}"


class ServiceLocation(models.Model):
    """A specific service counter or queueing point within an office."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name="service_locations")
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "org_service_location"
        unique_together = [("office", "name")]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.office.code}/{self.name}"
