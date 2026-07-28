"""Automation rule model and execution log."""
from __future__ import annotations

import uuid

from django.db import models


class AutomationRule(models.Model):
    class Trigger(models.TextChoices):
        TICKET_CREATED = "ticket.created", "Ticket created"
        TICKET_TRANSITIONED = "ticket.transitioned", "Ticket transitioned"
        SLA_AT_RISK = "sla.at_risk", "SLA at risk"
        SLA_BREACHED = "sla.breached", "SLA breached"
        TICKET_UNASSIGNED = "ticket.unassigned", "Ticket unassigned"

    class Action(models.TextChoices):
        ASSIGN_USER = "assign_user", "Assign user"
        SET_PRIORITY = "set_priority", "Set priority"
        NOTIFY = "notify", "Notify"
        ADD_NOTE = "add_note", "Add note"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    trigger = models.CharField(max_length=32, choices=Trigger.choices)
    conditions = models.JSONField(default=dict, blank=True)
    action = models.CharField(max_length=32, choices=Action.choices)
    action_params = models.JSONField(default=dict, blank=True)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "automation_rule"
        ordering = ("priority", "name")

    def __str__(self) -> str:
        return f"automation-rule:{self.pk}"


class AutomationExecution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="executions")
    aggregate = models.CharField(max_length=64)
    aggregate_id = models.CharField(max_length=64)
    success = models.BooleanField()
    detail = models.TextField(blank=True)
    executed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "automation_execution"

    def __str__(self) -> str:
        return f"automation-execution:{self.pk}"
