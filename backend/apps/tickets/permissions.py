"""Ticket action permissions and assignment eligibility."""
from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.identity_access.models import User

from .models import Ticket

DOMAIN_GROUPS = {
    "operational": {"ops-agents", "ops-supervisors"},
    "it": {"it-agents", "it-leads"},
}
REASSIGN_GROUPS = {"ops-supervisors", "it-leads", "system-admins"}


def user_groups(user: User) -> set[str]:
    """Return all durable and request-local group names for a user."""
    groups = set(user.keycloak_groups or [])
    groups.update(getattr(user, "_groups", []) or [])
    if user.pk:
        groups.update(user.groups.values_list("name", flat=True))
    return groups


def can_reassign(user: User) -> bool:
    groups = user_groups(user)
    return "auditors" not in groups and bool(groups & REASSIGN_GROUPS)


def can_change_confidentiality(user: User) -> bool:
    return can_reassign(user)


def can_update_work_state(user: User, ticket: Ticket) -> bool:
    groups = user_groups(user)
    if "auditors" in groups or not user.is_active:
        return False
    allowed = DOMAIN_GROUPS.get(ticket.domain, set()) | {"system-admins"}
    return bool(groups & allowed)


def _persisted_group_query(group_names: set[str]) -> Q:
    query = Q()
    for group_name in group_names:
        query |= Q(keycloak_groups__contains=[group_name]) | Q(groups__name=group_name)
    return query


def eligible_assignee_queryset(ticket: Ticket) -> QuerySet[User]:
    """Return active non-auditors eligible to own work in the ticket domain."""
    allowed_groups = DOMAIN_GROUPS.get(ticket.domain, set()) | {"system-admins"}
    eligible = _persisted_group_query(allowed_groups)
    auditor = _persisted_group_query({"auditors"})
    return User.objects.filter(is_active=True).filter(eligible).exclude(auditor).distinct()
