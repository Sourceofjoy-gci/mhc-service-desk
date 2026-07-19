"""Workflow definition: statuses, valid transitions, required fields.

The workflow engine reads these tables to decide whether a transition is
allowed (FR-038, FR-040). Transitions are data, not code.
"""
from __future__ import annotations

import uuid

from django.db import models


class Status(models.Model):
    """A possible state for a ticket within a domain's workflow."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    domain = models.CharField(max_length=16, choices=[("operational", "Operational"), ("it", "IT")])
    is_terminal = models.BooleanField(default=False)
    is_initial = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    public_label = models.CharField(
        max_length=128,
        blank=True,
        help_text="Friendly label exposed to the requester (PRD §29.5)",
    )

    class Meta:
        db_table = "workflow_status"
        ordering = ("domain", "order")
        constraints = [
            models.UniqueConstraint(fields=["domain", "code"], name="uniq_status_domain_code"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.domain}:{self.code}"


class Transition(models.Model):
    """An allowed status change for a given domain."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=16)
    from_status = models.ForeignKey(
        Status, on_delete=models.CASCADE, related_name="transitions_from"
    )
    to_status = models.ForeignKey(
        Status, on_delete=models.CASCADE, related_name="transitions_to"
    )
    name = models.CharField(max_length=128)
    required_role = models.CharField(max_length=64, blank=True)
    required_fields = models.JSONField(default=list, blank=True)
    sets_resolution = models.BooleanField(
        default=False,
        help_text="If true, the transition requires a resolution code + summary (FR-022)",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "workflow_transition"
        unique_together = [("domain", "from_status", "to_status")]


class TransitionHistory(models.Model):
    """Append-only record of every status change. Drives reporting and audit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(
        "tickets.Ticket", on_delete=models.CASCADE, related_name="transition_history"
    )
    from_status = models.ForeignKey(
        Status, on_delete=models.PROTECT, null=True, related_name="+"
    )
    to_status = models.ForeignKey(Status, on_delete=models.PROTECT, related_name="+")
    actor_subject = models.CharField(max_length=255, db_index=True)
    reason = models.TextField(blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "workflow_transition_history"
        ordering = ("-occurred_at",)
