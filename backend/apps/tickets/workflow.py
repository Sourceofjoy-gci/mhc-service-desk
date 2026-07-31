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

from .eligibility import is_auditor_identity, matching_actor_role_aliases
from .models import Ticket


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
    # Auditor authority only tightens access and is always read afresh. The
    # assignment service reaches this check while holding the same transaction's
    # actor-authority locks, so these non-locking reads observe the proven facts
    # without adding a competing lock order.
    if (
        not actor.is_active
        or authority.auditor_identity
        or "auditor" in authority.capabilities
        or is_auditor_identity(actor)
        or not ticket_is_in_scope
    ):
        return transitions.none()

    groups = matching_actor_role_aliases(
        ticket,
        actor,
        snapshot=authority,
    )
    if groups & {"admin", "admin-scope", "system-admins"}:
        return transitions.order_by("to_status__order", "to_status__code")
    return transitions.filter(
        Q(required_role="") | Q(required_role__in=groups)
    ).order_by("to_status__order", "to_status__code")
