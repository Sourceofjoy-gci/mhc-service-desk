"""Ticket action permissions and assignment eligibility."""
from __future__ import annotations

from django.db.models import QuerySet

from apps.identity_access.models import User
from apps.identity_access.scope import (
    get_authority_snapshot,
    get_effective_role_grants,
    is_auditor,
    scope_ticket_queryset,
)

from .eligibility import eligible_assignees, is_eligible_assignee
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
    groups = user_groups(user)
    return (
        not user.is_active
        or is_auditor(user, request=request)
        or "auditors" in groups
    )


def can_assign(
    user: User,
    *,
    ticket: Ticket | None = None,
    request: object | None = None,
) -> bool:
    if _cannot_mutate(user, request=request):
        return False
    if ticket is not None:
        authority = get_authority_snapshot(user, request=request)
        if not scope_ticket_queryset(
            user,
            Ticket.objects.filter(pk=ticket.pk),
            snapshot=authority,
        ).exists():
            return False
    return bool(user_groups(user) & REASSIGN_GROUPS)


def can_reassign(
    user: User,
    *,
    ticket: Ticket | None = None,
    request: object | None = None,
) -> bool:
    return can_assign(user, ticket=ticket, request=request)


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
    authority = get_authority_snapshot(user, request=request)
    if not scope_ticket_queryset(
        user,
        Ticket.objects.filter(pk=ticket.pk),
        snapshot=authority,
    ).exists():
        return False
    groups = user_groups(user)
    if any(scope.domain == "admin" for scope in authority.scopes):
        return True
    allowed = DOMAIN_GROUPS.get(ticket.domain, set()) | {"system-admins"}
    if groups & allowed:
        return True
    return is_eligible_assignee(ticket, user)


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
