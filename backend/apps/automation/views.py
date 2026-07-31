"""Automation rule API + lightweight executor.

The executor here is intentionally narrow — no code execution, no eval,
no shell. The PRD requires that automation be data-driven, versioned and
audited.
"""
from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.scope import ScopePermission
from apps.tickets.models import Ticket

from .models import AutomationExecution, AutomationRule

logger = logging.getLogger(__name__)


class AutomationRuleSerializer(serializers.ModelSerializer[AutomationRule]):
    class Meta:
        model = AutomationRule
        fields = (
            "id", "name", "description", "trigger", "conditions",
            "action", "action_params", "priority", "is_active",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class AutomationRuleViewSet(viewsets.ModelViewSet[AutomationRule]):
    queryset = AutomationRule.objects.all()
    serializer_class = AutomationRuleSerializer
    authentication_classes = [KeycloakJWTAuthentication]
    permission_classes = [IsAuthenticated, ScopePermission]


def evaluate_rules(*, trigger: str, ticket: Ticket) -> int:
    """Apply all active rules that match ``trigger`` against ``ticket``.

    Returns the number of successful executions. Failures are logged with
    the rule name and never roll back the triggering event.
    """
    count = 0
    rules = AutomationRule.objects.filter(
        trigger=trigger,
        is_active=True,
    ).order_by("priority", "name")
    for rule in rules:
        try:
            ok = _apply_action(rule, ticket)
            AutomationExecution.objects.create(
                rule=rule,
                aggregate="ticket",
                aggregate_id=str(ticket.id),
                success=ok,
                detail="ok" if ok else "skipped",
            )
            if ok:
                count += 1
        except Exception as exc:  # noqa: BLE001
            AutomationExecution.objects.create(
                rule=rule,
                aggregate="ticket",
                aggregate_id=str(ticket.id),
                success=False,
                detail=str(exc)[:2000],
            )
            logger.exception("automation_rule_failed", extra={"rule": rule.name})
    return count


@transaction.atomic
def _apply_action(rule: AutomationRule, ticket: Ticket) -> bool:
    from apps.tickets.events import record_ticket_event

    actor_subject = f"automation:{rule.name}"
    if rule.action == AutomationRule.Action.ASSIGN_USER:
        username = rule.action_params.get("username")
        if not username:
            return False
        from apps.identity_access.models import User
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return False
        from apps.tickets.assignment import assign_ticket_by_system
        from apps.tickets.services import TicketValidationError

        configured_reason = rule.action_params.get("reason")
        reason = (
            configured_reason.strip()
            if isinstance(configured_reason, str)
            else ""
        )
        if not reason:
            reason = f"Automation rule {rule.id} assigned ticket to {username}."
        try:
            assign_ticket_by_system(
                ticket_id=ticket.id,
                assignee_id=user.id,
                actor_subject=f"automation:{rule.id}",
                actor_display_name=f"Automation rule: {rule.name}",
                source_process="automation.rule",
                reason=reason,
            )
        except TicketValidationError:
            return False
        return True
    if rule.action == AutomationRule.Action.SET_PRIORITY:
        p = rule.action_params.get("priority")
        if p not in ("P1", "P2", "P3", "P4"):
            return False
        previous_priority = ticket.priority
        ticket.priority = p
        ticket.save(update_fields=["priority", "updated_at"])
        record_ticket_event(
            ticket=ticket,
            actor_subject=actor_subject,
            action="ticket.priority.changed",
            before={"priority": previous_priority},
            after={"priority": p},
            metadata={"rule": rule.name},
        )
        return True
    if rule.action == AutomationRule.Action.ADD_NOTE:
        body = rule.action_params.get("body", "")
        if not body:
            return False
        from apps.tickets.services import add_internal_note
        add_internal_note(ticket=ticket, body=body, author_subject=f"automation:{rule.name}")
        return True
    if rule.action == AutomationRule.Action.NOTIFY:
        # Placeholder — a real implementation would push to notifications/email/WhatsApp.
        logger.info("automation.notify", extra={"ticket": ticket.number, "rule": rule.name})
        return True
    return False
