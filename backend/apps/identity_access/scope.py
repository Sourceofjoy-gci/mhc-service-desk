"""Authorisation scope helpers.

Authorisation is enforced **server-side** on every endpoint. Scopes combine
a domain (operational | it), an office, a service, and an optional queue.
The frontend never grants access — it only renders what the backend approves.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q, QuerySet
from rest_framework import permissions


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


def has_scope(user, required: Scope) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    scopes = getattr(user, "_scopes", None) or []
    return any(s.matches(required) for s in scopes)


def get_user_scopes(user) -> list[Scope]:
    """Compute a user's scopes from their Keycloak group memberships.

    Group-to-scope mapping (P0 baseline):
        ops-agents          -> operational
        ops-supervisors     -> operational
        it-agents           -> it
        it-leads            -> it
        security-responders -> operational + it (restricted only)
        system-admins       -> admin
        auditors            -> audit (read-only across domains)
    """
    if not user or not user.is_authenticated:
        return []
    if user.is_superuser:
        return [Scope(domain="admin")]
    groups = set(getattr(user, "_groups", []) or [])
    scopes: list[Scope] = []
    if groups & {"ops-agents", "ops-supervisors"}:
        scopes.append(Scope(domain="operational"))
    if groups & {"it-agents", "it-leads"}:
        scopes.append(Scope(domain="it"))
    if "security-responders" in groups:
        scopes.append(Scope(domain="operational", restricted_only=True))
        scopes.append(Scope(domain="it", restricted_only=True))
    if "system-admins" in groups:
        scopes.append(Scope(domain="admin"))
    if "auditors" in groups:
        scopes.append(Scope(domain="operational"))
        scopes.append(Scope(domain="it"))

    normalised: dict[tuple[str, str | None, str | None, str | None], Scope] = {}
    for scope in scopes:
        key = (scope.domain, scope.office_id, scope.service_id, scope.queue_id)
        existing = normalised.get(key)
        if existing is None or (existing.restricted_only and not scope.restricted_only):
            normalised[key] = scope
    return list(normalised.values())


def is_auditor(user) -> bool:
    return "auditors" in set(getattr(user, "_groups", []) or [])


def has_unrestricted_domain_scope(user, domain: str) -> bool:
    user._scopes = get_user_scopes(user)
    return any(
        scope.domain == "admin"
        or (scope.domain == domain and not scope.restricted_only)
        for scope in user._scopes
    )


def can_view_restricted(user) -> bool:
    """Restricted tickets (security, fraud, complaint) require a narrower
    audience. Only supervisors, leads, security responders, admins and
    auditors can see them (PRD §14.2, §23.1)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    groups = set(getattr(user, "_groups", []) or [])
    privileged = {
        "ops-supervisors", "it-leads", "security-responders",
        "system-admins", "auditors",
    }
    return bool(groups & privileged)


def scope_ticket_queryset(user, queryset: QuerySet) -> QuerySet:
    """Limit a ticket queryset to the caller's explicit scopes."""
    scopes = get_user_scopes(user)
    user._scopes = scopes
    branches: list[Q] = []
    restricted_access = can_view_restricted(user)

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
        elif not restricted_access:
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
