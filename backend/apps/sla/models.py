"""SLA policies, business calendars, and persisted instances.

SLA state lives in PostgreSQL so queue restarts cannot lose timers
(PRD §25.3, FR-054). A periodic worker reads these rows and dispatches
notifications or escalations.
"""

from __future__ import annotations

import uuid
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class BusinessCalendar(models.Model):
    """An ordered list of business hours and holidays for SLA math."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    timezone = models.CharField(max_length=64, default="Africa/Mbabane")
    # business hours per ISO weekday (1=Mon..7=Sun); empty list = closed
    weekday_hours = models.JSONField(
        default=dict,
        help_text="e.g. {'1': [{'start': '08:00', 'end': '17:00'}]}",
    )
    # ISO date strings (YYYY-MM-DD) treated as holidays
    holidays = models.JSONField(default=list)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sla_calendar"

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValidationError({"timezone": "Enter a valid IANA timezone name."}) from exc

        if not isinstance(self.weekday_hours, dict):
            raise ValidationError({"weekday_hours": "Business hours must be keyed by ISO weekday."})

        errors: list[str] = []
        for day_key, raw_intervals in self.weekday_hours.items():
            if day_key not in {str(day) for day in range(1, 8)} or not isinstance(
                raw_intervals, list
            ):
                errors.append(f"Invalid ISO weekday entry: {day_key}.")
                continue
            intervals: list[tuple[time, time]] = []
            for raw_interval in raw_intervals:
                try:
                    start = time.fromisoformat(raw_interval["start"])
                    end = time.fromisoformat(raw_interval["end"])
                except (KeyError, TypeError, ValueError):
                    errors.append(f"Invalid interval for weekday {day_key}.")
                    continue
                if end <= start:
                    errors.append(f"Interval end must follow start for weekday {day_key}.")
                    continue
                intervals.append((start, end))
            intervals.sort()
            for previous, current in zip(intervals, intervals[1:], strict=False):
                if current[0] < previous[1]:
                    errors.append(f"Intervals for weekday {day_key} overlap.")
        if errors:
            raise ValidationError({"weekday_hours": errors})


class SlaPolicy(models.Model):
    """A named bundle of SLA targets for a domain/priority combination."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    domain = models.CharField(max_length=16, choices=[("operational", "Operational"), ("it", "IT")])
    priority = models.CharField(max_length=8)
    calendar = models.ForeignKey(
        BusinessCalendar, on_delete=models.PROTECT, related_name="policies"
    )
    acknowledgement_minutes = models.PositiveIntegerField(default=0)
    first_response_minutes = models.PositiveIntegerField()
    update_interval_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()
    warn_at_percent = models.PositiveIntegerField(default=75)
    escalation_percent = models.PositiveIntegerField(default=90)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sla_policy"
        unique_together = [("domain", "priority", "name")]

    def __str__(self) -> str:
        return f"{self.name} ({self.domain}/{self.priority})"


class SlaInstance(models.Model):
    """A live SLA timer for one ticket (FR-054)."""

    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED_REQUESTER = "paused_requester", "Paused — requester"
        PAUSED_INTERNAL = "paused_internal", "Paused — internal"
        PAUSED_IT = "paused_it", "Paused — IT"
        MET = "met", "Met"
        BREACHED = "breached", "Breached"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="sla_instances"
    )
    policy = models.ForeignKey(SlaPolicy, on_delete=models.PROTECT, related_name="instances")
    kind = models.CharField(max_length=32)  # acknowledgement | first_response | update | resolution
    state = models.CharField(max_length=24, choices=State.choices, default=State.ACTIVE)
    started_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField()
    consumed_business_seconds = models.PositiveIntegerField(default=0)
    remaining_business_seconds = models.PositiveIntegerField(null=True, blank=True)
    remaining_business_microseconds = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    breached_at = models.DateTimeField(null=True, blank=True)
    breach_reason = models.TextField(blank=True)
    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    warn_notified_at = models.DateTimeField(null=True, blank=True)
    escalation_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sla_instance"
        indexes = [
            models.Index(fields=["state", "due_at"]),
            models.Index(fields=["ticket", "kind"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.ticket_id} ({self.state})"


class SlaPauseHistory(models.Model):
    """Why and when an SLA was paused or resumed (PRD §17.1 audit)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(
        SlaInstance, on_delete=models.CASCADE, related_name="pause_history"
    )
    state = models.CharField(max_length=24)
    reason = models.CharField(max_length=128)
    actor_subject = models.CharField(max_length=255, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sla_pause_history"
        ordering = ("-at",)

    def __str__(self) -> str:
        return f"sla-pause:{self.instance_id} ({self.state})"
