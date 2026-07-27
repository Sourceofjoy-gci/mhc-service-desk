"""Authorisation scope helpers.

Authorisation is enforced **server-side** on every endpoint. Scopes combine
a domain (operational | it), an office, a service, and an optional queue.
The frontend never grants access — it only renders what the backend approves.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework import permissions

_DEFAULT_ROLE_SCOPES = {
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
}
_AUDITOR_ROLES = {"auditor", "auditors"}
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
_SCOPE_DIMENSIONS = ("office", "service", "queue")
_VALID_SCOPE_KEYS = {
    "domain",
    "restricted_only",
    *(
        key
        for dimension in _SCOPE_DIMENSIONS
        for key in (dimension, f"{dimension}_id")
    ),
}


@dataclass(frozen=True)
class Scope:
    domain: str          # "operational" | "it" | "admin" | "audit"
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


ScopeKey = tuple[str, str | None, str | None, str | None]


@dataclass(frozen=True)
class AuthoritySnapshot:
    """One immutable, request-local view of a user's effective authority."""

    scopes: tuple[Scope, ...] = ()
    capabilities: frozenset[str] = frozenset()
    restricted_scope_keys: frozenset[ScopeKey] = frozenset()


def has_scope(user, required: Scope) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    scopes = getattr(user, "_scopes", None) or []
    return any(s.matches(required) for s in scopes)


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


def _validated_scope_id(raw_scope: dict, name: str) -> tuple[bool, str | None]:
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


def _validated_role_scopes(assignment) -> tuple[Scope, ...] | None:
    """Validate one persisted assignment atomically.

    ``None`` means the assignment is malformed. An empty tuple is a valid but
    authority-free assignment (for example, an unknown role with no scopes).
    """
    configured_scopes = assignment.role.scopes
    if configured_scopes == []:
        raw_scopes = _DEFAULT_ROLE_SCOPES.get(
            assignment.role.keycloak_role,
            (),
        )
    elif isinstance(configured_scopes, list):
        raw_scopes = configured_scopes
    else:
        return None

    scopes: list[Scope] = []
    for raw_scope in raw_scopes:
        if not isinstance(raw_scope, dict) or not set(raw_scope) <= _VALID_SCOPE_KEYS:
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

        office_id = (
            str(assignment.office_id)
            if assignment.office_id is not None
            else identifiers["office"]
        )
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


def _active_persisted_assignments(user) -> list | None:
    """Return active assignments, preserving ``None`` for the group fallback."""
    assignments = getattr(user, "user_roles", None)
    if assignments is None or not getattr(user, "pk", None):
        return None

    persisted = list(assignments.select_related("role", "office").all())
    if not persisted:
        return None

    now = timezone.now()
    return [
        assignment
        for assignment in persisted
        if assignment.expires_at is None or assignment.expires_at > now
    ]


def _snapshot_from_persisted(assignments: list) -> AuthoritySnapshot:
    scopes: list[Scope] = []
    capabilities: set[str] = set()
    restricted_scope_keys: set[ScopeKey] = set()

    for assignment in assignments:
        assignment_scopes = _validated_role_scopes(assignment)
        if not assignment_scopes:
            continue

        scopes.extend(assignment_scopes)
        role_name = assignment.role.keycloak_role
        if role_name in _AUDITOR_ROLES:
            capabilities.add("auditor")
        if role_name in _RESTRICTED_VIEW_ROLES:
            restricted_scope_keys.update(map(_scope_key, assignment_scopes))
        restricted_scope_keys.update(
            _scope_key(scope) for scope in assignment_scopes if scope.restricted_only
        )

    return AuthoritySnapshot(
        scopes=tuple(_normalise_scopes(scopes)),
        capabilities=frozenset(capabilities),
        restricted_scope_keys=frozenset(restricted_scope_keys),
    )


def _snapshot_from_groups(user) -> AuthoritySnapshot:
    groups = set(getattr(user, "_groups", []) or [])
    scopes: list[Scope] = []
    capabilities: set[str] = set()
    restricted_scope_keys: set[ScopeKey] = set()

    def add_scope(scope: Scope, *, can_view_restricted_rows: bool = False):
        scopes.append(scope)
        if can_view_restricted_rows:
            restricted_scope_keys.add(_scope_key(scope))

    if "ops-agents" in groups:
        add_scope(Scope(domain="operational"))
    if "ops-supervisors" in groups:
        add_scope(
            Scope(domain="operational"),
            can_view_restricted_rows=True,
        )
    if "it-agents" in groups:
        add_scope(Scope(domain="it"))
    if "it-leads" in groups:
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
    if "system-admins" in groups:
        add_scope(Scope(domain="admin"), can_view_restricted_rows=True)
    if "auditors" in groups:
        capabilities.add("auditor")
        add_scope(Scope(domain="operational"), can_view_restricted_rows=True)
        add_scope(Scope(domain="it"), can_view_restricted_rows=True)

    return AuthoritySnapshot(
        scopes=tuple(_normalise_scopes(scopes)),
        capabilities=frozenset(capabilities),
        restricted_scope_keys=frozenset(restricted_scope_keys),
    )


def _build_authority_snapshot(user) -> AuthoritySnapshot:
    if not user or not user.is_authenticated:
        return AuthoritySnapshot()
    if user.is_superuser:
        admin_scope = Scope(domain="admin")
        return AuthoritySnapshot(
            scopes=(admin_scope,),
            restricted_scope_keys=frozenset({_scope_key(admin_scope)}),
        )

    assignments = _active_persisted_assignments(user)
    if assignments is not None:
        return _snapshot_from_persisted(assignments)
    return _snapshot_from_groups(user)


def _authority_snapshot(user) -> AuthoritySnapshot:
    """Return the immutable authority snapshot shared by one user/request."""
    snapshot = getattr(user, "_authority_snapshot", None) if user else None
    if isinstance(snapshot, AuthoritySnapshot):
        return snapshot

    snapshot = _build_authority_snapshot(user)
    if user is not None:
        user._authority_snapshot = snapshot
    return snapshot


def get_user_scopes(user) -> list[Scope]:
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
    return list(_authority_snapshot(user).scopes)


def is_auditor(user) -> bool:
    return "auditor" in _authority_snapshot(user).capabilities


def has_unrestricted_domain_scope(user, domain: str) -> bool:
    user._scopes = list(_authority_snapshot(user).scopes)
    return any(
        scope.domain == "admin"
        or (scope.domain == domain and not scope.restricted_only)
        for scope in user._scopes
    )


def can_view_restricted(user) -> bool:
    """Restricted tickets (security, fraud, complaint) require a narrower
    audience. Only supervisors, leads, security responders, admins and
    auditors can see them (PRD §14.2, §23.1)."""
    return bool(_authority_snapshot(user).restricted_scope_keys)


def scope_ticket_queryset(user, queryset: QuerySet) -> QuerySet:
    """Limit a ticket queryset to the caller's explicit scopes."""
    snapshot = _authority_snapshot(user)
    scopes = list(snapshot.scopes)
    user._scopes = scopes
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
        elif _scope_key(scope) not in snapshot.restricted_scope_keys:
            branch &= ~Q(confidentiality="restricted")
        branches.append(branch)

    if not branches:
        return queryset.none()

    combined = branches[0]
    for branch in branches[1:]:
        combined |= branch
    return queryset.filter(combined)


def attach_scopes(request):
    """DRF authenticator-friendly helper: set ``request.user._scopes``."""
    request.user._scopes = get_user_scopes(request.user)
    return request.user


def public_endpoint(fn):  # pragma: no cover - marker decorator
    """Marker for endpoints that bypass authentication."""
    fn._public = True
    return fn


class ScopePermission(permissions.BasePermission):
    """DRF permission factory tied to a required scope."""

    required_scope: Scope | None = None

    def has_permission(self, request, view):
        if getattr(view, "_public", False):
            return True
        if is_auditor(request.user) and request.method not in permissions.SAFE_METHODS:
            return False
        scope = getattr(view, "required_scope", None) or self.required_scope
        if scope is None:
            return bool(request.user and request.user.is_authenticated)
        attach_scopes(request)
        return has_scope(request.user, scope)


def scope_required(domain: str, **kwargs):
    """Class decorator that attaches a required scope to a DRF view."""
    required = Scope(domain=domain, **kwargs)

    def deco(cls):
        cls.required_scope = required
        cls.permission_classes = [ScopePermission]
        return cls

    return deco
