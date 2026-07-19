"""Authorisation scope helpers.

Authorisation is enforced **server-side** on every endpoint. Scopes combine
a domain (operational | it), an office, a service, and an optional queue.
The frontend never grants access — it only renders what the backend approves.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Iterable

from rest_framework import permissions


@dataclass(frozen=True)
class Scope:
    domain: str          # "operational" | "it" | "admin" | "audit"
    office_id: str | None = None
    service_id: str | None = None
    queue_id: str | None = None

    def matches(self, other: "Scope") -> bool:
        if self.domain == "admin":
            return True
        if self.domain != other.domain:
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
    if "system-admins" in groups:
        scopes.append(Scope(domain="admin"))
    if "auditors" in groups:
        scopes.append(Scope(domain="operational"))
        scopes.append(Scope(domain="it"))
    return scopes


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
