"""Tests for the scope-based authorisation helpers."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.identity_access.scope import (
    Scope,
    ScopePermission,
    get_user_scopes,
    has_scope,
    has_unrestricted_domain_scope,
    scope_ticket_queryset,
)
from apps.tickets.models import Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _user_with_scopes(*scopes: Scope):
    user = type(
        "U",
        (),
        {"is_authenticated": True, "is_superuser": False, "_scopes": list(scopes)},
    )()
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


def test_security_responder_scopes_are_restricted_only():
    user = type(
        "U",
        (),
        {
            "is_authenticated": True,
            "is_superuser": False,
            "_groups": ["security-responders"],
        },
    )()

    scopes = get_user_scopes(user)

    assert {(scope.domain, scope.restricted_only) for scope in scopes} == {
        ("operational", True),
        ("it", True),
    }
    assert not has_unrestricted_domain_scope(user, "operational")


def test_broader_group_wins_over_restricted_only_scope():
    user = type(
        "U",
        (),
        {
            "is_authenticated": True,
            "is_superuser": False,
            "_groups": ["security-responders", "ops-agents"],
        },
    )()

    assert has_unrestricted_domain_scope(user, "operational")
    assert not has_unrestricted_domain_scope(user, "it")


def _ticket(*, basic_world, number, domain, title, confidentiality):
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    return Ticket.objects.create(
        number=number,
        domain=domain,
        title=title,
        status=Status.objects.get(domain=domain, code="new"),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        confidentiality=confidentiality,
    )


def test_ticket_queryset_enforces_restricted_only_and_privileged_access(basic_world):
    _ticket(
        basic_world=basic_world,
        number="OP-202607-000001",
        domain="operational",
        title="Operational normal",
        confidentiality="normal",
    )
    _ticket(
        basic_world=basic_world,
        number="OP-202607-000002",
        domain="operational",
        title="Operational restricted",
        confidentiality="restricted",
    )
    _ticket(
        basic_world=basic_world,
        number="IT-202607-000001",
        domain="it",
        title="IT normal",
        confidentiality="normal",
    )
    _ticket(
        basic_world=basic_world,
        number="IT-202607-000002",
        domain="it",
        title="IT restricted",
        confidentiality="restricted",
    )

    def visible_titles(groups):
        user = type(
            "U",
            (),
            {"is_authenticated": True, "is_superuser": False, "_groups": groups},
        )()
        queryset = scope_ticket_queryset(user, Ticket.objects.all())
        return set(queryset.values_list("title", flat=True))

    assert visible_titles(["security-responders"]) == {
        "Operational restricted",
        "IT restricted",
    }
    assert visible_titles(["ops-agents"]) == {"Operational normal"}
    assert visible_titles(["ops-supervisors"]) == {
        "Operational normal",
        "Operational restricted",
    }


def test_auditors_are_read_only():
    user = type(
        "U",
        (),
        {"is_authenticated": True, "is_superuser": False, "_groups": ["auditors"]},
    )()
    permission = ScopePermission()
    view = SimpleNamespace()

    assert permission.has_permission(SimpleNamespace(user=user, method="GET"), view)
    assert not permission.has_permission(SimpleNamespace(user=user, method="POST"), view)
