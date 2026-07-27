"""Ticket action permissions and assignment eligibility."""
from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.identity_access.models import User, UserRole
from apps.identity_access.scope import is_auditor

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


def _cannot_mutate(user: User, *, request=None) -> bool:
    groups = user_groups(user)
    return (
        not user.is_active
        or is_auditor(user, request=request)
        or "auditors" in groups
    )


def can_reassign(
    user: User,
    *,
    ticket: Ticket | None = None,
    request=None,
) -> bool:
    if _cannot_mutate(user, request=request):
        return False
    if ticket is not None and not can_update_work_state(
        user,
        ticket,
        request=request,
    ):
        return False
    return bool(user_groups(user) & REASSIGN_GROUPS)


def can_change_confidentiality(
    user: User,
    *,
    ticket: Ticket | None = None,
    request=None,
) -> bool:
    return can_reassign(user, ticket=ticket, request=request)


def can_update_work_state(user: User, ticket: Ticket, *, request=None) -> bool:
    groups = user_groups(user)
    if _cannot_mutate(user, request=request):
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
    active_persisted_auditors = UserRole.objects.filter(
        role__keycloak_role__in={"auditor", "auditors"},
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
    return (
        User.objects.filter(is_active=True)
        .filter(eligible)
        .exclude(auditor)
        .exclude(id__in=active_persisted_auditors.values("user_id"))
        .distinct()
    )
