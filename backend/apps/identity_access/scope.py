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
        return has_scope(request.user, scope)
