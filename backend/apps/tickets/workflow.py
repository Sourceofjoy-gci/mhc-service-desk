"""Server-derived ticket workflow capabilities."""
from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.identity_access.models import User
from apps.identity_access.scope import (
    AuthoritySnapshot,
    get_authority_snapshot,
    scope_ticket_queryset,
)
from apps.workflow.models import Transition

from .models import Ticket
from .permissions import user_groups


def available_transitions(
    ticket: Ticket,
    actor: object,
    *,
    request: object | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> QuerySet[Transition]:
    """Return active current-state transitions the actor may execute."""
    transitions = Transition.objects.filter(
        domain=ticket.domain,
        from_status=ticket.status,
        is_active=True,
    ).select_related("to_status")
    if not isinstance(actor, User) or not actor.is_authenticated:
        return transitions.none()
    authority = snapshot or get_authority_snapshot(actor, request=request)
    ticket_is_in_scope = scope_ticket_queryset(
        actor,
        Ticket.objects.filter(pk=ticket.pk),
        snapshot=authority,
    ).exists()
    if (
        not actor.is_active
        or "auditor" in authority.capabilities
        or not ticket_is_in_scope
    ):
        return transitions.none()

    groups = user_groups(actor)
    if any(scope.domain == "admin" for scope in authority.scopes):
        return transitions.order_by("to_status__order", "to_status__code")
    return transitions.filter(
        Q(required_role="") | Q(required_role__in=groups)
    ).order_by("to_status__order", "to_status__code")
