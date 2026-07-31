"""Exact, explainable eligibility for internal ticket ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from django.utils import timezone

from apps.identity_access.models import User, UserRole
from apps.identity_access.scope import (
    AuthoritySnapshot,
    EffectiveRoleGrant,
    Scope,
    can_view_restricted,
    get_authority_snapshot,
    scope_ticket_queryset,
)
from apps.identity_access.scope import (
    _scope_key as scope_key,
)
from apps.identity_access.scope import (
    _snapshot_from_groups as snapshot_from_groups,
)
from apps.identity_access.scope import (
    _snapshot_from_persisted as snapshot_from_persisted,
)
from apps.identity_access.scope import (
    _validated_role_scopes as validated_role_scopes,
)

from .custody import CustodyParty
from .models import Ticket


@dataclass(frozen=True)
class AssigneeCandidate:
    id: UUID
    username: str
    display_name: str
    designations: tuple[str, ...]
    team_labels: tuple[str, ...]


@dataclass(frozen=True)
class Designation:
    role_key: str
    display_name: str
    team_label: str


DESIGNATIONS: tuple[Designation, ...] = (
    Designation("master", "Master", "Office Leadership"),
    Designation("deputy-master", "Deputy Master", "Office Leadership"),
    Designation("assistant-master", "Assistant Master", "Office Leadership"),
    Designation("assistant-accountant", "Assistant Accountant", "Finance"),
    Designation("accountant", "Accountant", "Finance"),
    Designation("senior-accountant", "Senior Accountant", "Finance"),
    Designation("principal-accountant", "Principal Accountant", "Finance"),
    Designation("financial-controller", "Financial Controller", "Finance"),
    Designation("estate-examiner", "Estate Examiner", "Estate Administration"),
    Designation("records-clerk", "Records Clerk", "Records and Data"),
    Designation("data-clerk", "Data Clerk", "Records and Data"),
)

_DESIGNATION_BY_KEY = {item.role_key: item for item in DESIGNATIONS}
_AUDITOR_ROLE_KEYS = {"auditor", "auditors"}
_RESTRICTED_ROLE_KEYS = {
    "supervisor-operational",
    "ops-supervisors",
    "lead-it",
    "it-leads",
    "admin",
    "system-admins",
    "security-responders",
}
_LEGACY_ROLE_DETAILS: dict[str, tuple[str, str, str]] = {
    "agent-operational": ("Operational Agent", "Operational", "operational"),
    "ops-agents": ("Operational Agent", "Operational", "operational"),
    "supervisor-operational": (
        "Operational Supervisor",
        "Operational",
        "operational",
    ),
    "ops-supervisors": (
        "Operational Supervisor",
        "Operational",
        "operational",
    ),
    "agent-it": ("IT Agent", "IT", "it"),
    "it-agents": ("IT Agent", "IT", "it"),
    "lead-it": ("IT Lead", "IT", "it"),
    "it-leads": ("IT Lead", "IT", "it"),
}
_ROLE_ALIASES: dict[str, frozenset[str]] = {
    "agent-operational": frozenset({"agent-operational", "ops-agents"}),
    "ops-agents": frozenset({"agent-operational", "ops-agents"}),
    "supervisor-operational": frozenset(
        {"supervisor-operational", "ops-supervisors"}
    ),
    "ops-supervisors": frozenset(
        {"supervisor-operational", "ops-supervisors"}
    ),
    "agent-it": frozenset({"agent-it", "it-agents"}),
    "it-agents": frozenset({"agent-it", "it-agents"}),
    "lead-it": frozenset({"lead-it", "it-leads"}),
    "it-leads": frozenset({"lead-it", "it-leads"}),
    "admin": frozenset({"admin", "system-admins"}),
    "system-admins": frozenset({"admin", "system-admins"}),
}
_GROUP_FALLBACK_ROLE_KEYS = {
    "ops-agents",
    "ops-supervisors",
    "it-agents",
    "it-leads",
    "system-admins",
}


@dataclass(frozen=True)
class _FunctionalMatch:
    role_key: str
    display_name: str
    team_label: str
    primary_designation: bool


def _prefetched_assignments(user: User) -> list[UserRole]:
    prefetched = getattr(user, "_prefetched_objects_cache", {}).get("user_roles")
    if prefetched is not None:
        return list(prefetched)
    return list(user.user_roles.select_related("role", "office").all())


def _active_assignments(
    assignments: list[UserRole],
    *,
    now: datetime,
) -> list[UserRole]:
    return [
        assignment
        for assignment in assignments
        if assignment.expires_at is None or assignment.expires_at > now
    ]


def _effective_groups(user: User) -> set[str]:
    groups = {
        group
        for group in (user.keycloak_groups or [])
        if isinstance(group, str)
    }
    raw_request_groups = getattr(user, "_groups", ())
    if isinstance(raw_request_groups, list | tuple | set | frozenset):
        groups.update(
            group for group in raw_request_groups if isinstance(group, str)
        )
    prefetched = getattr(user, "_prefetched_objects_cache", {}).get("groups")
    if prefetched is not None:
        groups.update(group.name for group in prefetched)
    elif user.pk:
        groups.update(user.groups.values_list("name", flat=True))
    return groups


def _authority_for_candidate(
    user: User,
    *,
    all_assignments: list[UserRole],
    active_assignments: list[UserRole],
    groups: set[str],
) -> AuthoritySnapshot:
    if active_assignments:
        return snapshot_from_persisted(cast(Any, active_assignments))
    return snapshot_from_groups(SimpleNamespace(_groups=groups))


def _scope_matches_ticket(scope: Scope, ticket: Ticket) -> bool:
    if scope.domain != ticket.domain:
        return False
    dimensions = (
        (scope.office_id, ticket.office_id),
        (scope.service_id, ticket.service_id),
        (scope.queue_id, ticket.queue_id),
    )
    return all(
        configured is None or configured == str(actual)
        for configured, actual in dimensions
    )


def _assignment_scope_matches_ticket(
    assignment: UserRole,
    scope: Scope,
    ticket: Ticket,
    *,
    scope_index: int,
) -> bool:
    if assignment.office_id is not None and assignment.office_id != ticket.office_id:
        return False
    configured_scopes = assignment.role.scopes
    if isinstance(configured_scopes, list) and configured_scopes:
        raw_scope = configured_scopes[scope_index]
        if isinstance(raw_scope, dict):
            configured_office = raw_scope.get(
                "office",
                raw_scope.get("office_id"),
            )
            if (
                configured_office is not None
                and str(configured_office) != str(ticket.office_id)
            ):
                return False
    return _scope_matches_ticket(scope, ticket)


def _ticket_visible_in_authority(
    ticket: Ticket,
    authority: AuthoritySnapshot,
) -> bool:
    for scope in authority.scopes:
        if scope.domain != "admin" and scope.domain != ticket.domain:
            continue
        dimensions = (
            (scope.office_id, ticket.office_id),
            (scope.service_id, ticket.service_id),
            (scope.queue_id, ticket.queue_id),
        )
        if any(
            configured is not None and configured != str(actual)
            for configured, actual in dimensions
        ):
            continue
        if scope.restricted_only:
            if ticket.confidentiality != Ticket.Confidentiality.RESTRICTED:
                continue
        elif (
            ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
            and scope_key(scope) not in authority.restricted_scope_keys
        ):
            continue
        return True
    return False


def _functional_matches(
    ticket: Ticket,
    *,
    active_assignments: list[UserRole],
    groups: set[str],
    has_active_persisted_assignments: bool,
) -> tuple[_FunctionalMatch, ...]:
    matches: list[_FunctionalMatch] = []
    for assignment in active_assignments:
        role_key = assignment.role.keycloak_role
        designation = _DESIGNATION_BY_KEY.get(role_key)
        legacy = _LEGACY_ROLE_DETAILS.get(role_key)
        if designation is None and legacy is None:
            continue
        scopes = validated_role_scopes(cast(Any, assignment))
        if not scopes or not any(
            _assignment_scope_matches_ticket(
                assignment,
                scope,
                ticket,
                scope_index=index,
            )
            for index, scope in enumerate(scopes)
        ):
            continue
        if designation is not None:
            matches.append(
                _FunctionalMatch(
                    role_key=role_key,
                    display_name=designation.display_name,
                    team_label=designation.team_label,
                    primary_designation=True,
                )
            )
        elif legacy is not None:
            _, team_label, _ = legacy
            matches.append(
                _FunctionalMatch(
                    role_key=role_key,
                    display_name=assignment.role.name,
                    team_label=team_label,
                    primary_designation=False,
                )
            )

    if not has_active_persisted_assignments:
        for role_key, (display_name, team_label, domain) in _LEGACY_ROLE_DETAILS.items():
            if role_key not in groups or domain != ticket.domain:
                continue
            matches.append(
                _FunctionalMatch(
                    role_key=role_key,
                    display_name=display_name,
                    team_label=team_label,
                    primary_designation=False,
                )
            )
    return tuple(matches)


def is_auditor_identity(
    user: User,
    *,
    active_assignments: list[UserRole] | None = None,
    groups: set[str] | None = None,
) -> bool:
    """Apply the read-only auditor boundary across every identity source."""
    resolved_assignments = (
        active_assignments
        if active_assignments is not None
        else _active_assignments(_prefetched_assignments(user), now=timezone.now())
    )
    resolved_groups = groups if groups is not None else _effective_groups(user)
    return bool(
        _AUDITOR_ROLE_KEYS & resolved_groups
        or any(
            assignment.role.keycloak_role in _AUDITOR_ROLE_KEYS
            for assignment in resolved_assignments
        )
    )


def has_active_persisted_assignments(user: User) -> bool:
    return bool(
        _active_assignments(_prefetched_assignments(user), now=timezone.now())
    )


def _matching_grant_role_aliases(
    ticket: Ticket,
    grants: tuple[EffectiveRoleGrant, ...],
    *,
    authority: AuthoritySnapshot,
) -> set[str]:
    aliases: set[str] = set()
    for grant in grants:
        role_key = grant.role_key
        matching_role_scopes = [
            scope
            for scope in grant.scopes
            if _role_grant_scope_matches_ticket(
                grant,
                scope,
                ticket,
            )
        ]
        if any(scope.domain == "admin" for scope in matching_role_scopes):
            aliases.add("admin-scope")
        if role_key in _DESIGNATION_BY_KEY:
            if _ticket_visible_in_authority(ticket, authority) and any(
                _scope_matches_ticket(scope, ticket) for scope in grant.scopes
            ):
                aliases.update(
                    _ROLE_ALIASES[
                        "agent-operational"
                        if ticket.domain == Ticket.Domain.OPERATIONAL
                        else "agent-it"
                    ]
                )
            continue
        role_aliases = _ROLE_ALIASES.get(role_key)
        if role_aliases and matching_role_scopes:
            aliases.update(role_aliases)
    return aliases


def _role_grant_scope_matches_ticket(
    grant: EffectiveRoleGrant,
    scope: Scope,
    ticket: Ticket,
) -> bool:
    if scope.domain != "admin" and scope.domain != ticket.domain:
        return False
    dimensions = (
        (scope.office_id, ticket.office_id),
        (scope.service_id, ticket.service_id),
        (scope.queue_id, ticket.queue_id),
    )
    if any(
        configured is not None and configured != str(actual)
        for configured, actual in dimensions
    ):
        return False
    if scope.restricted_only:
        return ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
    if ticket.confidentiality == Ticket.Confidentiality.RESTRICTED:
        return grant.role_key in _RESTRICTED_ROLE_KEYS
    return True


def matching_actor_role_aliases(
    ticket: Ticket,
    user: User,
    *,
    snapshot: AuthoritySnapshot | None = None,
) -> frozenset[str]:
    """Return only roles whose own effective scope covers this ticket."""
    if not user.is_active:
        return frozenset()
    authority = snapshot or get_authority_snapshot(user)
    if "auditor" in authority.capabilities:
        return frozenset()
    if is_auditor_identity(user):
        return frozenset()
    if user.is_superuser:
        return _ROLE_ALIASES["admin"]

    if authority.uses_persisted_roles:
        return frozenset(
            _matching_grant_role_aliases(
                ticket,
                authority.role_grants,
                authority=authority,
            )
        )
    if not _ticket_visible_in_authority(ticket, authority):
        return frozenset()

    aliases: set[str] = set()
    for role_key in _GROUP_FALLBACK_ROLE_KEYS & authority.group_role_keys:
        if role_key == "system-admins":
            aliases.update(_ROLE_ALIASES[role_key])
            continue
        details = _LEGACY_ROLE_DETAILS[role_key]
        if details[2] == ticket.domain:
            aliases.update(_ROLE_ALIASES[role_key])
    return frozenset(aliases)


def _candidate_for_user(
    ticket: Ticket,
    user: User,
    *,
    authority: AuthoritySnapshot | None = None,
    require_database_scope_check: bool,
) -> AssigneeCandidate | None:
    if not user.is_active:
        return None
    all_assignments = _prefetched_assignments(user)
    active_assignments = _active_assignments(all_assignments, now=timezone.now())
    groups = _effective_groups(user)
    if is_auditor_identity(
        user,
        active_assignments=active_assignments,
        groups=groups,
    ):
        return None
    resolved_authority = authority or _authority_for_candidate(
        user,
        all_assignments=all_assignments,
        active_assignments=active_assignments,
        groups=groups,
    )
    if "auditor" in resolved_authority.capabilities:
        return None
    if (
        ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
        and not can_view_restricted(user, snapshot=resolved_authority)
    ):
        return None
    if require_database_scope_check:
        if not scope_ticket_queryset(
            user,
            Ticket.objects.filter(pk=ticket.pk),
            snapshot=resolved_authority,
        ).exists():
            return None
    elif not _ticket_visible_in_authority(ticket, resolved_authority):
        # Bulk candidate loading uses the same immutable authority fields in
        # memory so visibility does not add one query per candidate.
        return None

    matches = _functional_matches(
        ticket,
        active_assignments=active_assignments,
        groups=groups,
        has_active_persisted_assignments=bool(active_assignments),
    )
    if not matches:
        return None

    designation_order = {
        item.display_name: index for index, item in enumerate(DESIGNATIONS)
    }
    designations = tuple(
        sorted(
            {match.display_name for match in matches},
            key=lambda value: (designation_order.get(value, len(DESIGNATIONS)), value),
        )
    )
    team_labels = tuple(sorted({match.team_label for match in matches}))
    return AssigneeCandidate(
        id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        designations=designations,
        team_labels=team_labels,
    )


def eligible_assignees(
    ticket: Ticket,
    *,
    search: str = "",
) -> tuple[AssigneeCandidate, ...]:
    """Return active ownership candidates without per-user database queries."""
    users = User.objects.filter(is_active=True).prefetch_related(
        "user_roles__role",
        "user_roles__office",
        "groups",
    )
    candidates = tuple(
        candidate
        for user in users
        if (
            candidate := _candidate_for_user(
                ticket,
                user,
                require_database_scope_check=False,
            )
        )
    )
    query = search.strip().casefold()
    if query:
        candidates = tuple(
            candidate
            for candidate in candidates
            if any(
                query in value.casefold()
                for value in (
                    candidate.display_name,
                    candidate.username,
                    *candidate.designations,
                    *candidate.team_labels,
                )
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.display_name.casefold(),
                item.username.casefold(),
                str(item.id),
            ),
        )
    )


def is_eligible_assignee(ticket: Ticket, user: User) -> bool:
    """Revalidate one target against canonical ticket visibility and scope."""
    return (
        _candidate_for_user(
            ticket,
            user,
            require_database_scope_check=True,
        )
        is not None
    )


def matching_designation_role_keys(ticket: Ticket, user: User) -> frozenset[str]:
    """Return primary designation grants that match this exact ticket."""
    all_assignments = _prefetched_assignments(user)
    active_assignments = _active_assignments(all_assignments, now=timezone.now())
    groups = _effective_groups(user)
    authority = get_authority_snapshot(user)
    if "auditor" in authority.capabilities or not _ticket_visible_in_authority(
        ticket,
        authority,
    ):
        return frozenset()
    return frozenset(
        match.role_key
        for match in _functional_matches(
            ticket,
            active_assignments=active_assignments,
            groups=groups,
            has_active_persisted_assignments=bool(active_assignments),
        )
        if match.primary_designation
    )


def custody_party_for_user(ticket: Ticket, user: User) -> CustodyParty:
    candidate = _candidate_for_user(
        ticket,
        user,
        require_database_scope_check=True,
    )
    return CustodyParty(
        id=str(user.id),
        subject=user.keycloak_subject,
        display_name=user.display_name or user.username,
        designations=candidate.designations if candidate else (),
        team_labels=candidate.team_labels if candidate else (),
    )
