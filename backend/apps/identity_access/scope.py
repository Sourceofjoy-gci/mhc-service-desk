"""Authorisation scope helpers.

Authorisation is enforced **server-side** on every endpoint. Scopes combine
a domain (operational | it), an office, a service, and an optional queue.
The frontend never grants access — it only renders what the backend approves.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, TypeGuard, TypeVar, runtime_checkable
from uuid import UUID

from django.db.models import Model, Q, QuerySet
from django.utils import timezone
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView

if TYPE_CHECKING:
    from apps.identity_access.models import User

type RawScope = dict[str, object]

_DEFAULT_ROLE_SCOPES: dict[str, tuple[RawScope, ...]] = {
    "agent-operational": ({"domain": "operational"},),
    "ops-agents": ({"domain": "operational"},),
    "supervisor-operational": ({"domain": "operational"},),
    "ops-supervisors": ({"domain": "operational"},),
    "agent-it": ({"domain": "it"},),
    "it-agents": ({"domain": "it"},),
    "lead-it": ({"domain": "it"},),
    "it-leads": ({"domain": "it"},),
    "admin": ({"domain": "admin"},),
    "system-admins": ({"domain": "admin"},),
    "auditor": ({"domain": "operational"}, {"domain": "it"}),
    "auditors": ({"domain": "operational"}, {"domain": "it"}),
    "security-responders": (
        {"domain": "operational", "restricted_only": True},
        {"domain": "it", "restricted_only": True},
    ),
    "service-desk-agents": ({"domain": "operational"},),
    "agent-servicedesk": ({"domain": "operational"},),
}
_AUDITOR_ROLES = {"auditor", "auditors"}
# The national service desk answers queries before the responsible office is
# known, so it is never bound to one office.
_SERVICE_DESK_ROLES = frozenset({"service-desk-agents", "agent-servicedesk"})
_RESTRICTED_VIEW_ROLES = {
    "supervisor-operational",
    "ops-supervisors",
    "lead-it",
    "it-leads",
    "admin",
    "system-admins",
    "auditor",
    "auditors",
    "security-responders",
}
_VALID_SCOPE_DOMAINS = {"operational", "it", "admin"}
_SCOPE_DIMENSIONS: tuple[str, ...] = ("office", "service", "queue")
_VALID_SCOPE_KEYS = {
    "domain",
    "restricted_only",
    *(key for dimension in _SCOPE_DIMENSIONS for key in (dimension, f"{dimension}_id")),
}

_ModelT = TypeVar("_ModelT", bound=Model)
_ViewT = TypeVar("_ViewT", bound=APIView)
_CallableT = TypeVar("_CallableT", bound=Callable[..., object])


class _RoleConfig(Protocol):
    keycloak_role: str
    name: str
    scopes: object


class _RoleAssignment(Protocol):
    role: _RoleConfig
    office_id: UUID | None
    expires_at: datetime | None


@runtime_checkable
class _AssignmentManager(Protocol):
    def select_related(self, *fields: str) -> _AssignmentManager: ...

    def all(self) -> Iterable[_RoleAssignment]: ...


def _is_string_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _is_authenticated(user: object) -> bool:
    return bool(getattr(user, "is_authenticated", False))


def _is_active(user: object) -> bool:
    return bool(getattr(user, "is_active", False))


def _has_active_identity(user: object) -> bool:
    return _is_authenticated(user) and _is_active(user)


def _is_superuser(user: object) -> bool:
    return bool(getattr(user, "is_superuser", False))


@dataclass(frozen=True)
class Scope:
    domain: str  # "operational" | "it" | "admin" | "audit"
    office_id: str | None = None
    service_id: str | None = None
    queue_id: str | None = None
    restricted_only: bool = False

    def matches(self, other: Scope) -> bool:
        if self.domain == "admin":
            return True
        if self.domain != other.domain:
            return False
        if self.restricted_only and not other.restricted_only:
            return False
        if self.office_id and other.office_id and self.office_id != other.office_id:
            return False
        if self.service_id and other.service_id and self.service_id != other.service_id:
            return False
        if self.queue_id and other.queue_id and self.queue_id != other.queue_id:
            return False
        return True


@dataclass(frozen=True)
class EffectiveRoleGrant:
    role_key: str
    role_name: str
    scopes: tuple[Scope, ...]
    office_id: UUID | None
    expires_at: datetime | None


ScopeKey = tuple[str, str | None, str | None, str | None]


@dataclass(frozen=True)
class AuthoritySnapshot:
    """One immutable, request-local view of a user's effective authority."""

    scopes: tuple[Scope, ...] = ()
    capabilities: frozenset[str] = frozenset()
    restricted_scope_keys: frozenset[ScopeKey] = frozenset()
    role_grants: tuple[EffectiveRoleGrant, ...] = ()
    group_role_keys: frozenset[str] = frozenset()
    uses_persisted_roles: bool = False
    auditor_identity: bool = False


def has_scope(user: object, required: Scope) -> bool:
    if not _has_active_identity(user):
        return False
    if _is_superuser(user):
        return True
    raw_scopes: object = getattr(user, "_scopes", None)
    if not isinstance(raw_scopes, list | tuple):
        return False
    return any(scope.matches(required) for scope in raw_scopes if isinstance(scope, Scope))


def _normalise_scopes(scopes: list[Scope]) -> list[Scope]:
    normalised: dict[ScopeKey, Scope] = {}
    for scope in scopes:
        key = _scope_key(scope)
        existing = normalised.get(key)
        if existing is None or (existing.restricted_only and not scope.restricted_only):
            normalised[key] = scope
    return list(normalised.values())


def _scope_key(scope: Scope) -> ScopeKey:
    return (scope.domain, scope.office_id, scope.service_id, scope.queue_id)


def _validated_scope_id(
    raw_scope: dict[str, object],
    name: str,
) -> tuple[bool, str | None]:
    keys = [key for key in (name, f"{name}_id") if key in raw_scope]
    if len(keys) > 1:
        return False, None
    if not keys or raw_scope[keys[0]] is None:
        return True, None

    value = raw_scope[keys[0]]
    if not isinstance(value, str):
        return False, None
    try:
        return True, str(UUID(value))
    except (AttributeError, ValueError):
        return False, None


def _validated_role_scopes(
    assignment: _RoleAssignment,
    *,
    preserve_configured_office: bool = False,
) -> tuple[Scope, ...] | None:
    """Validate one persisted assignment atomically.

    ``None`` means the assignment is malformed. An empty tuple is a valid but
    authority-free assignment (for example, an unknown role with no scopes).
    """
    configured_scopes = assignment.role.scopes
    if configured_scopes == []:
        raw_scopes: Sequence[object] = _DEFAULT_ROLE_SCOPES.get(
            assignment.role.keycloak_role,
            (),
        )
    elif isinstance(configured_scopes, list):
        raw_scopes = configured_scopes
    else:
        return None

    scopes: list[Scope] = []
    for raw_scope in raw_scopes:
        if not _is_string_object_dict(raw_scope) or not set(raw_scope) <= _VALID_SCOPE_KEYS:
            return None

        domain = raw_scope.get("domain")
        if not isinstance(domain, str) or domain not in _VALID_SCOPE_DOMAINS:
            return None

        restricted_only = raw_scope.get("restricted_only", False)
        if type(restricted_only) is not bool:
            return None

        identifiers: dict[str, str | None] = {}
        for dimension in _SCOPE_DIMENSIONS:
            valid, value = _validated_scope_id(raw_scope, dimension)
            if not valid:
                return None
            identifiers[dimension] = value

        office_id = identifiers["office"]
        if not preserve_configured_office and assignment.office_id is not None:
            office_id = str(assignment.office_id)
        scopes.append(
            Scope(
                domain=domain,
                office_id=office_id,
                service_id=identifiers["service"],
                queue_id=identifiers["queue"],
                restricted_only=restricted_only,
            )
        )
    return tuple(scopes)


def _active_persisted_assignments(
    user: object,
) -> list[_RoleAssignment] | None:
    """Return active assignments, preserving ``None`` for the group fallback."""
    assignments: object = getattr(user, "user_roles", None)
    if not isinstance(assignments, _AssignmentManager) or not getattr(user, "pk", None):
        return None

    prefetched_cache: object = getattr(user, "_prefetched_objects_cache", {})
    prefetched_assignments: object = None
    if isinstance(prefetched_cache, dict):
        prefetched_assignments = prefetched_cache.get("user_roles")
    if isinstance(prefetched_assignments, Iterable) and not isinstance(
        prefetched_assignments,
        str | bytes,
    ):
        persisted = list(prefetched_assignments)
    else:
        persisted = list(assignments.select_related("role", "office").all())
    if not persisted:
        return None

    now = timezone.now()
    active = [
        assignment
        for assignment in persisted
        if assignment.expires_at is None or assignment.expires_at > now
    ]
    return active or None


def _effective_grants_from_assignments(
    assignments: Sequence[_RoleAssignment],
) -> tuple[EffectiveRoleGrant, ...]:
    grants: list[EffectiveRoleGrant] = []
    for assignment in assignments:
        scopes = _validated_role_scopes(
            assignment,
            preserve_configured_office=True,
        )
        if not scopes:
            continue
        grants.append(
            EffectiveRoleGrant(
                role_key=assignment.role.keycloak_role,
                role_name=getattr(
                    assignment.role,
                    "name",
                    assignment.role.keycloak_role,
                ),
                scopes=scopes,
                office_id=assignment.office_id,
                expires_at=assignment.expires_at,
            )
        )
    return tuple(
        sorted(
            grants,
            key=lambda grant: (
                grant.role_key,
                grant.office_id is not None,
                str(grant.office_id or ""),
            ),
        )
    )


def get_effective_role_grants(user: User) -> tuple[EffectiveRoleGrant, ...]:
    """Return validated active grants, ordered by role then office (None first)."""
    if not _has_active_identity(user):
        return ()

    assignments = _active_persisted_assignments(user)
    if not assignments:
        return ()
    return _effective_grants_from_assignments(assignments)


def _snapshot_from_persisted(
    assignments: Sequence[_RoleAssignment],
) -> AuthoritySnapshot:
    grants = _effective_grants_from_assignments(assignments)
    scopes: list[Scope] = []
    capabilities: set[str] = set()
    restricted_scope_keys: set[ScopeKey] = set()
    auditor_identity = any(
        assignment.role.keycloak_role in _AUDITOR_ROLES for assignment in assignments
    )

    for assignment in assignments:
        assignment_scopes = _validated_role_scopes(assignment)
        if not assignment_scopes:
            continue
        scopes.extend(assignment_scopes)
        role_key = assignment.role.keycloak_role
        if role_key in _AUDITOR_ROLES:
            capabilities.add("auditor")
        if role_key in _RESTRICTED_VIEW_ROLES:
            restricted_scope_keys.update(map(_scope_key, assignment_scopes))
        restricted_scope_keys.update(
            _scope_key(scope) for scope in assignment_scopes if scope.restricted_only
        )

    return AuthoritySnapshot(
        scopes=tuple(_normalise_scopes(scopes)),
        capabilities=frozenset(capabilities),
        restricted_scope_keys=frozenset(restricted_scope_keys),
        role_grants=grants,
        uses_persisted_roles=True,
        auditor_identity=auditor_identity,
    )


def _string_group_names(raw_groups: object) -> set[str]:
    if not isinstance(raw_groups, list | tuple | set | frozenset):
        return set()
    return {group for group in raw_groups if isinstance(group, str)}


def _effective_group_names(user: object) -> set[str]:
    groups = _string_group_names(getattr(user, "keycloak_groups", ()))
    groups.update(_string_group_names(getattr(user, "_groups", ())))

    prefetched_cache: object = getattr(user, "_prefetched_objects_cache", {})
    prefetched_groups: object = None
    if isinstance(prefetched_cache, dict):
        prefetched_groups = prefetched_cache.get("groups")
    if isinstance(prefetched_groups, Iterable) and not isinstance(
        prefetched_groups,
        str | bytes,
    ):
        groups.update(
            name
            for group in prefetched_groups
            if isinstance((name := getattr(group, "name", None)), str)
        )
        return groups

    group_manager: object = getattr(user, "groups", None)
    values_list: object = getattr(group_manager, "values_list", None)
    if getattr(user, "pk", None) and callable(values_list):
        durable_names: object = values_list("name", flat=True)
        if isinstance(durable_names, Iterable):
            groups.update(name for name in durable_names if isinstance(name, str))
    return groups


def _snapshot_from_groups(user: object) -> AuthoritySnapshot:
    groups = _effective_group_names(user)
    scopes: list[Scope] = []
    capabilities: set[str] = set()
    restricted_scope_keys: set[ScopeKey] = set()

    def add_scope(
        scope: Scope,
        *,
        can_view_restricted_rows: bool = False,
    ) -> None:
        scopes.append(scope)
        if can_view_restricted_rows:
            restricted_scope_keys.add(_scope_key(scope))

    if groups & {"ops-agents", "agent-operational"}:
        add_scope(Scope(domain="operational"))
    if groups & {"ops-supervisors", "supervisor-operational"}:
        add_scope(
            Scope(domain="operational"),
            can_view_restricted_rows=True,
        )
    if groups & {"it-agents", "agent-it"}:
        add_scope(Scope(domain="it"))
    if groups & {"it-leads", "lead-it"}:
        add_scope(Scope(domain="it"), can_view_restricted_rows=True)
    if "security-responders" in groups:
        add_scope(
            Scope(domain="operational", restricted_only=True),
            can_view_restricted_rows=True,
        )
        add_scope(
            Scope(domain="it", restricted_only=True),
            can_view_restricted_rows=True,
        )
    if groups & _SERVICE_DESK_ROLES:
        add_scope(Scope(domain="operational"))
    if groups & {"system-admins", "admin"}:
        add_scope(Scope(domain="admin"), can_view_restricted_rows=True)
    if groups & {"auditors", "auditor"}:
        capabilities.add("auditor")
        add_scope(Scope(domain="operational"), can_view_restricted_rows=True)
        add_scope(Scope(domain="it"), can_view_restricted_rows=True)

    return AuthoritySnapshot(
        scopes=tuple(_normalise_scopes(scopes)),
        capabilities=frozenset(capabilities),
        restricted_scope_keys=frozenset(restricted_scope_keys),
        group_role_keys=frozenset(groups),
        auditor_identity=bool(_AUDITOR_ROLES & groups),
    )


def _build_authority_snapshot(user: object) -> AuthoritySnapshot:
    if not user or not _has_active_identity(user):
        return AuthoritySnapshot()

    assignments = _active_persisted_assignments(user)
    if assignments is not None:
        resolved = _snapshot_from_persisted(assignments)
    else:
        resolved = _snapshot_from_groups(user)

    if not _is_superuser(user):
        return resolved

    admin_scope = Scope(domain="admin")
    return AuthoritySnapshot(
        scopes=(admin_scope,),
        capabilities=resolved.capabilities,
        restricted_scope_keys=frozenset({_scope_key(admin_scope)}),
        role_grants=resolved.role_grants,
        group_role_keys=resolved.group_role_keys,
        uses_persisted_roles=resolved.uses_persisted_roles,
        auditor_identity=resolved.auditor_identity,
    )


def get_authority_snapshot(
    user: object,
    *,
    request: object | None = None,
) -> AuthoritySnapshot:
    """Resolve authority once per request, or freshly for a standalone caller."""
    if not _has_active_identity(user):
        inactive_snapshot = AuthoritySnapshot()
        if request is not None:
            vars(request)["_authority_snapshot"] = inactive_snapshot
            vars(request)["_authority_snapshot_user"] = user
        return inactive_snapshot

    if request is not None:
        cached_snapshot: object = getattr(request, "_authority_snapshot", None)
        snapshot_user = getattr(request, "_authority_snapshot_user", None)
        if isinstance(cached_snapshot, AuthoritySnapshot) and snapshot_user is user:
            return cached_snapshot

    snapshot = _build_authority_snapshot(user)
    if request is not None:
        vars(request)["_authority_snapshot"] = snapshot
        vars(request)["_authority_snapshot_user"] = user
    return snapshot


def _resolved_authority_snapshot(
    user: object,
    *,
    request: object | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> AuthoritySnapshot:
    if snapshot is not None:
        return snapshot
    return get_authority_snapshot(user, request=request)


def get_user_scopes(
    user: object,
    *,
    request: object | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> list[Scope]:
    """Compute canonical scopes from persisted assignments or group fallback.

    Active ``UserRole`` assignments take precedence so an office, service,
    or queue boundary cannot be broadened by a domain-wide group. Users with
    no persisted assignments use the P0 Keycloak group mapping:
        ops-agents          -> operational
        ops-supervisors     -> operational
        it-agents           -> it
        it-leads            -> it
        security-responders -> operational + it (restricted only)
        system-admins       -> admin
        auditors            -> audit (read-only across domains)
    """
    return list(_resolved_authority_snapshot(user, request=request, snapshot=snapshot).scopes)


def is_auditor(
    user: object,
    *,
    request: object | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> bool:
    authority = _resolved_authority_snapshot(user, request=request, snapshot=snapshot)
    return authority.auditor_identity or "auditor" in authority.capabilities


def has_unrestricted_domain_scope(
    user: object,
    domain: str,
    *,
    request: object | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> bool:
    authority = _resolved_authority_snapshot(user, request=request, snapshot=snapshot)
    scopes = list(authority.scopes)
    vars(user)["_scopes"] = scopes
    return any(
        scope.domain == "admin" or (scope.domain == domain and not scope.restricted_only)
        for scope in scopes
    )


def can_view_restricted(
    user: object,
    *,
    request: object | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> bool:
    """Restricted tickets (security, fraud, complaint) require a narrower
    audience. Only supervisors, leads, security responders, admins and
    auditors can see them (PRD §14.2, §23.1)."""
    authority = _resolved_authority_snapshot(user, request=request, snapshot=snapshot)
    return bool(authority.restricted_scope_keys)


def scope_ticket_queryset(
    user: object,
    queryset: QuerySet[_ModelT],
    *,
    request: object | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> QuerySet[_ModelT]:
    """Limit a ticket queryset to the caller's explicit scopes."""
    authority = _resolved_authority_snapshot(user, request=request, snapshot=snapshot)
    scopes = list(authority.scopes)
    vars(user)["_scopes"] = scopes
    branches: list[Q] = []

    for scope in scopes:
        if scope.domain == "admin":
            branch = Q(pk__isnull=False)
        elif scope.domain in {"operational", "it"}:
            branch = Q(domain=scope.domain)
        else:
            continue
        if scope.office_id:
            branch &= Q(office_id=scope.office_id)
        if scope.service_id:
            branch &= Q(service_id=scope.service_id)
        if scope.queue_id:
            branch &= Q(queue_id=scope.queue_id)
        if scope.restricted_only:
            branch &= Q(confidentiality="restricted")
        elif _scope_key(scope) not in authority.restricted_scope_keys:
            branch &= ~Q(confidentiality="restricted")
        branches.append(branch)

    if not branches:
        return queryset.none()

    combined = branches[0]
    for branch in branches[1:]:
        combined |= branch
    return queryset.filter(combined)


def attach_scopes(request: Request) -> object:
    """DRF authenticator-friendly helper: set ``request.user._scopes``."""
    vars(request.user)["_scopes"] = get_user_scopes(request.user, request=request)
    return request.user


def public_endpoint(fn: _CallableT) -> _CallableT:  # pragma: no cover - marker decorator
    """Marker for endpoints that bypass authentication."""
    vars(fn)["_public"] = True
    return fn


class ScopePermission(permissions.BasePermission):
    """DRF permission factory tied to a required scope."""

    required_scope: Scope | None = None

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "_public", False):
            return True
        if not _has_active_identity(request.user):
            return False
        snapshot = get_authority_snapshot(request.user, request=request)
        if (
            is_auditor(request.user, snapshot=snapshot)
            and request.method not in permissions.SAFE_METHODS
        ):
            return False
        scope = getattr(view, "required_scope", None) or self.required_scope
        if scope is None:
            return bool(request.user and request.user.is_authenticated)
        attach_scopes(request)
        return has_scope(request.user, scope)


def scope_required(
    domain: str,
    *,
    office_id: str | None = None,
    service_id: str | None = None,
    queue_id: str | None = None,
    restricted_only: bool = False,
) -> Callable[[type[_ViewT]], type[_ViewT]]:
    """Class decorator that attaches a required scope to a DRF view."""
    required = Scope(
        domain=domain,
        office_id=office_id,
        service_id=service_id,
        queue_id=queue_id,
        restricted_only=restricted_only,
    )

    def deco(cls: type[_ViewT]) -> type[_ViewT]:
        type.__setattr__(cls, "required_scope", required)
        type.__setattr__(cls, "permission_classes", [ScopePermission])
        return cls

    return deco
