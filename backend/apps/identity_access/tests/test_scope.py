"""Tests for the scope-based authorisation helpers."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.catalogue.models import RequestType, Service
from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import (
    Scope,
    ScopePermission,
    can_view_restricted,
    get_user_scopes,
    has_scope,
    has_unrestricted_domain_scope,
    is_auditor,
    scope_ticket_queryset,
)
from apps.organisations.models import Office, ServiceLocation
from apps.tickets.models import Ticket
from apps.tickets.views import operational_dashboard
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


def _persisted_user(*, groups):
    user = User.objects.create(
        username=f"user-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
    )
    user._groups = groups
    return user


def _operational_service(*, code):
    service = Service.objects.create(code=code, name=code, domain="operational")
    request_type = RequestType.objects.create(
        service=service,
        code=f"{code}-TYPE",
        name=f"{code} request",
        default_priority="P3",
    )
    return service, request_type


def _ticket_for_scope(
    *,
    basic_world,
    number,
    title,
    office,
    service,
    request_type,
    queue,
    confidentiality="normal",
):
    return Ticket.objects.create(
        number=number,
        domain="operational",
        title=title,
        status=Status.objects.get(domain="operational", code="new"),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=request_type,
        office=office,
        queue=queue,
        confidentiality=confidentiality,
    )


def test_persisted_role_domain_and_office_override_replace_broad_group_scope(basic_world):
    user = _persisted_user(groups=["ops-agents"])
    role = Role.objects.create(
        keycloak_role="agent-operational",
        name="Operational agent",
        scopes=[],
    )
    UserRole.objects.create(user=user, role=role, office=basic_world["office"])

    assert get_user_scopes(user) == [
        Scope(domain="operational", office_id=str(basic_world["office"].id))
    ]


def test_persisted_scope_enforces_office_service_and_queue_ids(basic_world):
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="TST-2",
        name="Other Office",
    )
    scoped_service, scoped_type = _operational_service(code="SCOPED-SVC")
    other_service, other_type = _operational_service(code="OTHER-SVC")
    scoped_queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Scoped queue",
    )
    other_queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Other queue",
    )
    user = _persisted_user(groups=["ops-agents"])
    role = Role.objects.create(
        keycloak_role="scoped-operational",
        name="Scoped operational role",
        scopes=[
            {
                "domain": "operational",
                "office": str(other_office.id),
                "service": str(scoped_service.id),
                "queue": str(scoped_queue.id),
            }
        ],
    )
    UserRole.objects.create(user=user, role=role, office=basic_world["office"])

    _ticket_for_scope(
        basic_world=basic_world,
        number="OP-202607-100001",
        title="matches every dimension",
        office=basic_world["office"],
        service=scoped_service,
        request_type=scoped_type,
        queue=scoped_queue,
    )
    _ticket_for_scope(
        basic_world=basic_world,
        number="OP-202607-100002",
        title="wrong office",
        office=other_office,
        service=scoped_service,
        request_type=scoped_type,
        queue=scoped_queue,
    )
    _ticket_for_scope(
        basic_world=basic_world,
        number="OP-202607-100003",
        title="wrong service",
        office=basic_world["office"],
        service=other_service,
        request_type=other_type,
        queue=scoped_queue,
    )
    _ticket_for_scope(
        basic_world=basic_world,
        number="OP-202607-100004",
        title="wrong queue",
        office=basic_world["office"],
        service=scoped_service,
        request_type=scoped_type,
        queue=other_queue,
    )

    scopes = get_user_scopes(user)
    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert scopes == [
        Scope(
            domain="operational",
            office_id=str(basic_world["office"].id),
            service_id=str(scoped_service.id),
            queue_id=str(scoped_queue.id),
        )
    ]
    assert set(visible.values_list("title", flat=True)) == {"matches every dimension"}


def test_multiple_persisted_scopes_are_combined_with_or(basic_world):
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="TST-2",
        name="Other Office",
    )
    first_service, first_type = _operational_service(code="FIRST-SVC")
    second_service, second_type = _operational_service(code="SECOND-SVC")
    first_queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="First queue",
    )
    second_queue = ServiceLocation.objects.create(office=other_office, name="Second queue")
    user = _persisted_user(groups=["ops-agents"])
    first_role = Role.objects.create(
        keycloak_role="first-scoped-role",
        name="First scoped role",
        scopes=[
            {
                "domain": "operational",
                "service": str(first_service.id),
                "queue": str(first_queue.id),
            }
        ],
    )
    second_role = Role.objects.create(
        keycloak_role="second-scoped-role",
        name="Second scoped role",
        scopes=[
            {
                "domain": "operational",
                "service": str(second_service.id),
                "queue": str(second_queue.id),
            }
        ],
    )
    UserRole.objects.create(user=user, role=first_role, office=basic_world["office"])
    UserRole.objects.create(user=user, role=second_role, office=other_office)

    _ticket_for_scope(
        basic_world=basic_world,
        number="OP-202607-200001",
        title="first branch",
        office=basic_world["office"],
        service=first_service,
        request_type=first_type,
        queue=first_queue,
    )
    _ticket_for_scope(
        basic_world=basic_world,
        number="OP-202607-200002",
        title="second branch",
        office=other_office,
        service=second_service,
        request_type=second_type,
        queue=second_queue,
    )
    _ticket_for_scope(
        basic_world=basic_world,
        number="OP-202607-200003",
        title="mixed dimensions",
        office=basic_world["office"],
        service=second_service,
        request_type=second_type,
        queue=second_queue,
    )

    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert set(visible.values_list("title", flat=True)) == {
        "first branch",
        "second branch",
    }


def test_persisted_unrestricted_scope_replaces_duplicate_restricted_scope(basic_world):
    user = _persisted_user(groups=[])
    role = Role.objects.create(
        keycloak_role="combined-operational",
        name="Combined operational role",
        scopes=[
            {"domain": "operational", "restricted_only": True},
            {"domain": "operational", "restricted_only": False},
        ],
    )
    UserRole.objects.create(user=user, role=role, office=None)

    assert get_user_scopes(user) == [Scope(domain="operational", restricted_only=False)]

    _ticket(
        basic_world=basic_world,
        number="OP-202607-300001",
        domain="operational",
        title="Mixed normal",
        confidentiality="normal",
    )
    _ticket(
        basic_world=basic_world,
        number="OP-202607-300002",
        domain="operational",
        title="Mixed restricted",
        confidentiality="restricted",
    )

    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert set(visible.values_list("title", flat=True)) == {
        "Mixed normal",
        "Mixed restricted",
    }


@pytest.fixture
def _confidentiality_tickets(basic_world):
    for number, domain, title, confidentiality in (
        ("OP-202607-400001", "operational", "Operational normal", "normal"),
        ("OP-202607-400002", "operational", "Operational restricted", "restricted"),
        ("IT-202607-400001", "it", "IT normal", "normal"),
        ("IT-202607-400002", "it", "IT restricted", "restricted"),
    ):
        _ticket(
            basic_world=basic_world,
            number=number,
            domain=domain,
            title=title,
            confidentiality=confidentiality,
        )


def _assign_persisted_role(user, *, keycloak_role, scopes=None, expires_at=None):
    role = Role.objects.create(
        keycloak_role=keycloak_role,
        name=keycloak_role,
        scopes=[] if scopes is None else scopes,
    )
    return UserRole.objects.create(
        user=user,
        role=role,
        office=None,
        expires_at=expires_at,
    )


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_persisted_auditor_is_denied_every_unsafe_method(method):
    user = _persisted_user(groups=[])
    _assign_persisted_role(user, keycloak_role="auditor")

    permission = ScopePermission()
    request = SimpleNamespace(user=user, method=method)

    assert not permission.has_permission(request, SimpleNamespace())


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "authority_source",
    [
        "auditors-group",
        "persisted-auditor",
        "persisted-admin-and-auditor",
    ],
)
def test_superuser_auditor_is_denied_every_unsafe_method(method, authority_source):
    user = _persisted_user(groups=["auditors"] if authority_source == "auditors-group" else [])
    user.is_superuser = True
    if authority_source in {"persisted-auditor", "persisted-admin-and-auditor"}:
        _assign_persisted_role(user, keycloak_role="auditor")
    if authority_source == "persisted-admin-and-auditor":
        _assign_persisted_role(user, keycloak_role="admin")

    permission = ScopePermission()
    request = SimpleNamespace(user=user, method=method)

    assert not permission.has_permission(request, SimpleNamespace())


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_superuser_persisted_admin_suppresses_auditor_group_fallback(method):
    user = _persisted_user(groups=["auditors"])
    user.is_superuser = True
    _assign_persisted_role(user, keycloak_role="admin")

    permission = ScopePermission()
    request = SimpleNamespace(user=user, method=method)

    assert permission.has_permission(request, SimpleNamespace())


@pytest.mark.parametrize(
    ("keycloak_role", "expected_titles"),
    [
        (
            "supervisor-operational",
            {"Operational normal", "Operational restricted"},
        ),
        ("lead-it", {"IT normal", "IT restricted"}),
        (
            "admin",
            {
                "Operational normal",
                "Operational restricted",
                "IT normal",
                "IT restricted",
            },
        ),
        (
            "auditor",
            {
                "Operational normal",
                "Operational restricted",
                "IT normal",
                "IT restricted",
            },
        ),
        (
            "security-responders",
            {"Operational restricted", "IT restricted"},
        ),
    ],
)
@pytest.mark.usefixtures("_confidentiality_tickets")
def test_persisted_privileged_role_has_exact_restricted_visibility(
    keycloak_role,
    expected_titles,
):
    user = _persisted_user(groups=[])
    _assign_persisted_role(user, keycloak_role=keycloak_role)

    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert set(visible.values_list("title", flat=True)) == expected_titles


@pytest.mark.parametrize("assignment_kind", ["expired", "malformed", "unknown"])
@pytest.mark.usefixtures("_confidentiality_tickets")
def test_invalid_persisted_assignment_fails_closed_without_group_capability_fallback(
    assignment_kind,
):
    user = _persisted_user(groups=["auditors", "ops-supervisors"])
    if assignment_kind == "expired":
        _assign_persisted_role(
            user,
            keycloak_role="auditor",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
    elif assignment_kind == "malformed":
        _assign_persisted_role(
            user,
            keycloak_role="malformed-role",
            scopes=["not-a-scope", {"restricted_only": True}],
        )
    else:
        _assign_persisted_role(user, keycloak_role="unknown-role")

    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert get_user_scopes(user) == []
    assert not is_auditor(user)
    assert not can_view_restricted(user)
    assert not visible.exists()


@pytest.mark.parametrize(
    "raw_scopes",
    [
        pytest.param(1, id="scalar-top-level-json"),
        pytest.param({"domain": "operational"}, id="object-top-level-json"),
        pytest.param(
            [{"domain": "operational", "restricted_only": "false"}],
            id="string-boolean",
        ),
        pytest.param(
            [{"domain": "operational", "restricted_only": 1}],
            id="numeric-boolean",
        ),
        pytest.param(
            [{"domain": "finance"}],
            id="unknown-domain",
        ),
        pytest.param(
            [{"domain": "operational", "office": "not-a-uuid"}],
            id="invalid-office-id",
        ),
        pytest.param(
            [{"domain": "operational", "service": 123}],
            id="wrong-service-id-type",
        ),
        pytest.param(
            [{"domain": "operational", "queue_id": "not-a-uuid"}],
            id="invalid-queue-id",
        ),
    ],
)
@pytest.mark.usefixtures("_confidentiality_tickets")
def test_malformed_persisted_scope_schema_invalidates_the_entire_assignment(
    raw_scopes,
):
    user = _persisted_user(groups=["auditors", "ops-supervisors"])
    _assign_persisted_role(
        user,
        keycloak_role="malformed-schema-role",
        scopes=raw_scopes,
    )

    try:
        scopes = get_user_scopes(user)
        auditor = is_auditor(user)
        restricted = can_view_restricted(user)
        visible = scope_ticket_queryset(user, Ticket.objects.all())
        visible_exists = visible.exists()
    except Exception as exc:  # pragma: no cover - turns crashes into a red assertion
        pytest.fail(f"malformed persisted scope must fail closed, not raise: {exc!r}")

    assert scopes == []
    assert not auditor
    assert not restricted
    assert not visible_exists


def test_raw_restricted_grant_is_exact_to_its_same_domain_office_branch(basic_world):
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="BRANCH-2",
        name="Other branch office",
    )
    service, request_type = _operational_service(code="BRANCH-SVC")
    first_queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="First branch queue",
    )
    second_queue = ServiceLocation.objects.create(
        office=other_office,
        name="Second branch queue",
    )
    user = _persisted_user(groups=[])
    _assign_persisted_role(
        user,
        keycloak_role="branch-local-restricted",
        scopes=[
            {
                "domain": "operational",
                "office": str(basic_world["office"].id),
                "restricted_only": True,
            },
            {
                "domain": "operational",
                "office": str(other_office.id),
            },
        ],
    )

    for suffix, office, queue, confidentiality, title in (
        ("01", basic_world["office"], first_queue, "normal", "first normal"),
        (
            "02",
            basic_world["office"],
            first_queue,
            "restricted",
            "first restricted",
        ),
        ("03", other_office, second_queue, "normal", "second normal"),
        (
            "04",
            other_office,
            second_queue,
            "restricted",
            "second restricted",
        ),
    ):
        _ticket_for_scope(
            basic_world=basic_world,
            number=f"OP-202607-5000{suffix}",
            title=title,
            office=office,
            service=service,
            request_type=request_type,
            queue=queue,
            confidentiality=confidentiality,
        )

    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert set(visible.values_list("title", flat=True)) == {
        "first restricted",
        "second normal",
    }


@pytest.mark.usefixtures("_confidentiality_tickets")
def test_raw_restricted_grant_does_not_widen_an_unrelated_domain_branch():
    user = _persisted_user(groups=[])
    _assign_persisted_role(
        user,
        keycloak_role="cross-domain-restricted",
        scopes=[
            {"domain": "operational", "restricted_only": True},
            {"domain": "it"},
        ],
    )

    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert set(visible.values_list("title", flat=True)) == {
        "Operational restricted",
        "IT normal",
    }


@pytest.mark.usefixtures("_confidentiality_tickets")
def test_named_privileged_role_only_grants_restricted_rows_in_its_own_scopes():
    user = _persisted_user(groups=[])
    _assign_persisted_role(user, keycloak_role="supervisor-operational")
    _assign_persisted_role(
        user,
        keycloak_role="ordinary-it-role",
        scopes=[{"domain": "it"}],
    )

    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert set(visible.values_list("title", flat=True)) == {
        "Operational normal",
        "Operational restricted",
        "IT normal",
    }


class _ChangingAssignmentManager:
    def __init__(self, assignment):
        self.assignment = assignment
        self.read_count = 0

    def select_related(self, *args):
        return self

    def all(self):
        self.read_count += 1
        if self.read_count == 1:
            return [self.assignment]
        return []


class _RevocableAssignmentManager:
    def __init__(self, assignment):
        self.assignments = [assignment]
        self.read_count = 0

    def select_related(self, *args):
        return self

    def all(self):
        self.read_count += 1
        return list(self.assignments)

    def revoke(self):
        self.assignments = []


@pytest.mark.usefixtures("_confidentiality_tickets")
def test_ticket_scope_decision_uses_one_immutable_authority_snapshot():
    assignment = SimpleNamespace(
        role=SimpleNamespace(
            keycloak_role="ordinary-operational-role",
            scopes=[{"domain": "operational"}],
        ),
        office_id=None,
        expires_at=None,
    )
    manager = _ChangingAssignmentManager(assignment)
    user = SimpleNamespace(
        is_authenticated=True,
        is_superuser=False,
        pk=uuid4(),
        user_roles=manager,
        _groups=["auditors"],
    )

    visible = scope_ticket_queryset(user, Ticket.objects.all())

    assert manager.read_count == 1
    assert set(visible.values_list("title", flat=True)) == {"Operational normal"}


def test_reused_user_gets_fresh_authority_snapshot_on_the_next_request():
    assignment = SimpleNamespace(
        role=SimpleNamespace(
            keycloak_role="ordinary-operational-role",
            scopes=[{"domain": "operational"}],
        ),
        office_id=None,
        expires_at=None,
    )
    manager = _RevocableAssignmentManager(assignment)
    user = SimpleNamespace(
        is_authenticated=True,
        is_superuser=False,
        pk=uuid4(),
        user_roles=manager,
        _groups=[],
    )
    factory = APIRequestFactory()

    first_request = factory.get("/api/tickets/dashboard/operational/")
    force_authenticate(first_request, user=user)
    first_response = operational_dashboard(first_request)

    manager.revoke()
    second_request = factory.get("/api/tickets/dashboard/operational/")
    force_authenticate(second_request, user=user)
    second_response = operational_dashboard(second_request)

    assert first_response.status_code == 200
    assert second_response.status_code == 403
    assert manager.read_count == 2
