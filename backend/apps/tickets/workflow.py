"""Server-derived ticket workflow capabilities."""
from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.workflow.models import Transition

from .models import Ticket
from .permissions import can_update_work_state, user_groups


def available_transitions(ticket: Ticket, actor) -> QuerySet[Transition]:
    """Return active current-state transitions the actor may execute."""
    transitions = Transition.objects.filter(
        domain=ticket.domain,
        from_status=ticket.status,
        is_active=True,
    ).select_related("to_status")
    if (
        actor is None
        or not getattr(actor, "is_authenticated", False)
        or not can_update_work_state(actor, ticket)
    ):
        return transitions.none()

    groups = user_groups(actor)
    if actor.is_superuser or "system-admins" in groups:
        return transitions.order_by("to_status__order", "to_status__code")
    return transitions.filter(
        Q(required_role="") | Q(required_role__in=groups)
    ).order_by("to_status__order", "to_status__code")
