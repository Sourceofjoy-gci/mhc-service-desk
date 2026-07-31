"""Ticket action permissions and assignment eligibility."""
from __future__ import annotations

from django.db.models import QuerySet

from apps.identity_access.models import User
from apps.identity_access.scope import (
    get_authority_snapshot,
    get_effective_role_grants,
)

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
