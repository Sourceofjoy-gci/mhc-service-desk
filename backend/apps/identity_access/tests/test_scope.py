"""Tests for the scope-based authorisation helpers."""
from __future__ import annotations

from apps.identity_access.scope import Scope, has_scope


def _user_with_scopes(*scopes: Scope):
    user = type("U", (), {"is_authenticated": True, "is_superuser": False, "_scopes": list(scopes)})()
    return user


def test_admin_scope_matches_everything():
    admin = _user_with_scopes(Scope(domain="admin"))
    assert has_scope(admin, Scope(domain="operational", office_id="x"))


def test_same_domain_matches():
    user = _user_with_scopes(Scope(domain="operational", office_id="a"))
    assert has_scope(user, Scope(domain="operational", office_id="a"))


def test_cross_domain_does_not_match():
    user = _user_with_scopes(Scope(domain="it", office_id="a"))
    assert not has_scope(user, Scope(domain="operational", office_id="a"))


def test_office_scoping():
    user = _user_with_scopes(Scope(domain="operational", office_id="a"))
    assert not has_scope(user, Scope(domain="operational", office_id="b"))


def test_queue_scoping_strict():
    user = _user_with_scopes(Scope(domain="operational", queue_id="q1"))
    assert has_scope(user, Scope(domain="operational", queue_id="q1"))
    assert not has_scope(user, Scope(domain="operational", queue_id="q2"))
