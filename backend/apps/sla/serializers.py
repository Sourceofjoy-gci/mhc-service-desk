"""Read-model helpers for SLA clocks shown in ticket workspaces."""
from __future__ import annotations

from datetime import UTC, datetime

from django.utils import timezone

from apps.tickets.models import Ticket

from .models import SlaInstance


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def serialize_sla_clock(
    instance: SlaInstance | None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Normalize one persisted SLA into a non-negative display clock."""
    if instance is None:
        return {
            "state": "not_started",
            "due_at": None,
            "remaining_seconds": 0,
            "overdue_seconds": 0,
        }

    now = now or timezone.now()
    remaining = max(0, int((instance.due_at - now).total_seconds()))
    overdue = max(0, int((now - instance.due_at).total_seconds()))

    if instance.state == SlaInstance.State.ACTIVE:
        state = "running" if instance.due_at > now else "breached"
    elif instance.state in {
        SlaInstance.State.PAUSED_REQUESTER,
        SlaInstance.State.PAUSED_INTERNAL,
        SlaInstance.State.PAUSED_IT,
    }:
        state = "paused"
        overdue = 0
    elif instance.state == SlaInstance.State.MET:
        state = "met"
        remaining = 0
        overdue = 0
    elif instance.state == SlaInstance.State.BREACHED:
        state = "breached"
    else:
        state = "not_started"
        remaining = 0
        overdue = 0

    return {
        "state": state,
        "due_at": _iso_z(instance.due_at),
        "remaining_seconds": remaining,
        "overdue_seconds": overdue,
    }


def serialize_sla_clocks(
    ticket: Ticket,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return the two workspace SLA clocks from authoritative persisted rows."""
    instances = {
        instance.kind: instance
        for instance in ticket.sla_instances.filter(
            kind__in=("first_response", "resolution")
        ).order_by("created_at", "id")
    }
    now = now or timezone.now()
    return {
        kind: serialize_sla_clock(instances.get(kind), now)
        for kind in ("first_response", "resolution")
    }
