"""Ticket action permissions and assignment eligibility."""
from __future__ import annotations

from django.db.models import QuerySet
from rest_framework.request import Request

from apps.identity_access.models import User
from apps.identity_access.scope import (
    AuthoritySnapshot,
    Scope,
    get_authority_snapshot,
    get_effective_role_grants,
)
from apps.organisations.models import ServiceLocation

from .eligibility import (
    eligible_assignees,
    has_active_persisted_assignments,
    is_auditor_identity,
    matching_actor_role_aliases,
)
from .models import Ticket

DOMAIN_GROUPS = {
    "operational": {
        "agent-operational",
        "ops-agents",
        "supervisor-operational",
        "ops-supervisors",
    },
    "it": {"agent-it", "it-agents", "lead-it", "it-leads"},
}
REASSIGN_GROUPS = {
    "supervisor-operational",
    "ops-supervisors",
    "lead-it",
    "it-leads",
    "admin",
    "system-admins",
}


def user_groups(user: User) -> set[str]:
    """Return all durable and request-local group names for a user."""
    groups = set(user.keycloak_groups or [])
    groups.update(getattr(user, "_groups", []) or [])
    if user.pk:
        groups.update(user.groups.values_list("name", flat=True))
        groups.update(grant.role_key for grant in get_effective_role_grants(user))
    return groups


def _cannot_mutate(user: User, *, request: object | None = None) -> bool:
    del request
    return not user.is_active or is_auditor_identity(user)


def can_assign(
    user: User,
    *,
    ticket: Ticket | None = None,
    request: object | None = None,
) -> bool:
    if _cannot_mutate(user, request=request):
        return False
    if ticket is not None:
        authority = (
            get_authority_snapshot(user, request=request)
            if request is not None
            else None
        )
        return bool(
            matching_actor_role_aliases(
                ticket,
                user,
                snapshot=authority,
            )
            & REASSIGN_GROUPS
        )
    if user.is_superuser:
        return True
    if has_active_persisted_assignments(user):
        return bool(
            {
                grant.role_key
                for grant in get_effective_role_grants(user)
            }
            & REASSIGN_GROUPS
        )
    return bool(user_groups(user) & REASSIGN_GROUPS)


def can_reassign(
    user: User,
    *,
    ticket: Ticket | None = None,
    request: object | None = None,
) -> bool:
    return can_assign(user, ticket=ticket, request=request)


def _scope_covers_routing_result(
    scope: Scope,
    ticket: Ticket,
    queue: ServiceLocation | None,
    *,
    authority: AuthoritySnapshot,
) -> bool:
    if scope.domain != "admin" and scope.domain != ticket.domain:
        return False
    dimensions = (
        (scope.office_id, str(ticket.office_id)),
        (scope.service_id, str(ticket.service_id)),
        (scope.queue_id, str(queue.id) if queue is not None else None),
    )
    if any(configured is not None and configured != actual for configured, actual in dimensions):
        return False
    if scope.restricted_only:
        return ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
    if ticket.confidentiality != Ticket.Confidentiality.RESTRICTED:
        return True
    scope_key = (
        scope.domain,
        scope.office_id,
        scope.service_id,
        scope.queue_id,
    )
    return scope_key in authority.restricted_scope_keys


def _can_assign_with_snapshot(
    user: User,
    ticket: Ticket,
    *,
    request: object | None,
    snapshot: AuthoritySnapshot,
) -> bool:
    if _cannot_mutate(user, request=request):
        return False
    if snapshot.auditor_identity or "auditor" in snapshot.capabilities:
        return False
    return bool(
        matching_actor_role_aliases(ticket, user, snapshot=snapshot)
        & REASSIGN_GROUPS
    )


def can_unqueue_ticket(
    user: User,
    ticket: Ticket,
    *,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> bool:
    """Require explicit authority that remains valid after queue removal."""
    authority = snapshot or get_authority_snapshot(user, request=request)
    if not _can_assign_with_snapshot(
        user,
        ticket,
        request=request,
        snapshot=authority,
    ):
        return False
    return any(
        scope.queue_id is None
        and _scope_covers_routing_result(
            scope,
            ticket,
            None,
            authority=authority,
        )
        for scope in authority.scopes
    )


def can_route_ticket(
    user: User,
    ticket: Ticket,
    queue: ServiceLocation | None,
    *,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> bool:
    """Require assignment authority plus exact resulting queue scope."""
    authority = snapshot or get_authority_snapshot(user, request=request)
    if queue is None:
        return can_unqueue_ticket(
            user,
            ticket,
            request=request,
            snapshot=authority,
        )
    if not queue.is_active or queue.office_id != ticket.office_id:
        return False
    if not _can_assign_with_snapshot(
        user,
        ticket,
        request=request,
        snapshot=authority,
    ):
        return False
    return any(
        _scope_covers_routing_result(
            scope,
            ticket,
            queue,
            authority=authority,
        )
        for scope in authority.scopes
    )


def can_change_confidentiality(
    user: User,
    *,
    ticket: Ticket | None = None,
    request: object | None = None,
) -> bool:
    return can_assign(user, ticket=ticket, request=request)


def can_update_work_state(
    user: User,
    ticket: Ticket,
    *,
    request: object | None = None,
) -> bool:
    if _cannot_mutate(user, request=request):
        return False
    authority = (
        get_authority_snapshot(user, request=request)
        if request is not None
        else None
    )
    aliases = matching_actor_role_aliases(
        ticket,
        user,
        snapshot=authority,
    )
    allowed = DOMAIN_GROUPS.get(ticket.domain, set()) | {
        "admin",
        "admin-scope",
        "system-admins",
    }
    return bool(aliases & allowed)


def can_add_ticket_content(
    user: User,
    ticket: Ticket,
    *,
    request: object | None = None,
) -> bool:
    """Return whether the actor may add mutable content to this ticket."""
    return can_update_work_state(user, ticket, request=request)


def eligible_assignee_queryset(ticket: Ticket) -> QuerySet[User]:
    """Compatibility queryset backed by the exact eligibility service."""
    candidate_ids = [candidate.id for candidate in eligible_assignees(ticket)]
    return User.objects.filter(id__in=candidate_ids)
