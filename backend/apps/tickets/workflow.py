"""Server-derived ticket workflow capabilities."""
from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.identity_access.scope import AuthoritySnapshot, get_authority_snapshot
from apps.workflow.models import Transition

from .models import Ticket
from .permissions import user_groups


def _scope_key(scope) -> tuple[str, str | None, str | None, str | None]:
    return (scope.domain, scope.office_id, scope.service_id, scope.queue_id)


def _ticket_is_in_scope(ticket: Ticket, authority: AuthoritySnapshot) -> bool:
    for scope in authority.scopes:
        if scope.domain == "admin":
            return True
        if scope.domain != ticket.domain:
            continue
        if scope.office_id and scope.office_id != str(ticket.office_id):
            continue
        if scope.service_id and scope.service_id != str(ticket.service_id):
            continue
        if scope.queue_id and scope.queue_id != str(ticket.queue_id):
            continue
        if scope.restricted_only:
            if ticket.confidentiality == Ticket.Confidentiality.RESTRICTED:
                return True
            continue
        if (
            ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
            and _scope_key(scope) not in authority.restricted_scope_keys
        ):
            continue
        return True
    return False


def available_transitions(
    ticket: Ticket,
    actor,
    *,
    request=None,
    snapshot: AuthoritySnapshot | None = None,
) -> QuerySet[Transition]:
    """Return active current-state transitions the actor may execute."""
    transitions = Transition.objects.filter(
        domain=ticket.domain,
        from_status=ticket.status,
        is_active=True,
    ).select_related("to_status")
    if actor is None or not getattr(actor, "is_authenticated", False):
        return transitions.none()
    authority = snapshot or get_authority_snapshot(actor, request=request)
    if (
        not actor.is_active
        or "auditor" in authority.capabilities
        or not _ticket_is_in_scope(ticket, authority)
    ):
        return transitions.none()

    groups = user_groups(actor)
    if any(scope.domain == "admin" for scope in authority.scopes):
        return transitions.order_by("to_status__order", "to_status__code")
    return transitions.filter(
        Q(required_role="") | Q(required_role__in=groups)
    ).order_by("to_status__order", "to_status__code")
