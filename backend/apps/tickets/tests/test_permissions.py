from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth.models import Group

from apps.identity_access.models import Role, User, UserRole
from apps.tickets.models import Ticket
from apps.tickets.permissions import (
    can_add_ticket_content,
    can_assign,
    can_change_confidentiality,
    can_reassign,
    can_update_work_state,
    eligible_assignee_queryset,
    user_groups,
)
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db

DESIGNATION_KEYS = (
    "master",
    "deputy-master",
    "assistant-master",
    "assistant-accountant",
    "accountant",
    "senior-accountant",
    "principal-accountant",
    "financial-controller",
    "estate-examiner",
    "records-clerk",
    "data-clerk",
)


def _user(*, groups: list[str], active: bool = True) -> User:
    return User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        keycloak_groups=groups,
        is_active=active,
    )


@pytest.mark.parametrize(
    ("groups", "can_reassign_expected", "can_confidentiality_expected"),
    [
        (["ops-agents"], False, False),
        (["it-agents"], False, False),
        (["ops-supervisors"], True, True),
        (["it-leads"], True, True),
        (["system-admins"], True, True),
        (["auditors"], False, False),
        (["auditors", "ops-supervisors"], False, False),
    ],
)
def test_elevated_ticket_permissions(
    groups,
    can_reassign_expected,
    can_confidentiality_expected,
):
    user = _user(groups=groups)

    assert can_assign(user) is can_reassign_expected
    assert can_reassign(user) is can_reassign_expected
    assert can_change_confidentiality(user) is can_confidentiality_expected


def test_user_groups_combines_durable_request_and_django_groups():
    user = _user(groups=["ops-agents"])
    user._groups = ["ops-supervisors"]
    django_group = Group.objects.create(name="system-admins")
    user.groups.add(django_group)

    assert user_groups(user) == {
        "ops-agents",
        "ops-supervisors",
        "system-admins",
    }


def test_eligible_assignees_are_active_and_match_ticket_domain(basic_world):
    operational_agent = _user(groups=["ops-agents"])
    operational_supervisor = _user(groups=["ops-supervisors"])
    administrator = _user(groups=["system-admins"])
    _user(groups=["it-agents"])
    _user(groups=["ops-agents"], active=False)
    _user(groups=["auditors"])
    _user(groups=["ops-agents", "auditors"])
    persisted_auditor = _user(groups=["ops-agents"])
    auditor_role = Role.objects.create(keycloak_role="auditors", name="Auditor")
    UserRole.objects.create(user=persisted_auditor, role=auditor_role)
    status = Status.objects.get(domain="operational", code="new")
    ticket = Ticket.objects.create(
        number="OP-202607-900001",
        domain="operational",
        title="Assignment eligibility",
        status=status,
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    eligible_ids = set(eligible_assignee_queryset(ticket).values_list("id", flat=True))

    assert eligible_ids == {
        operational_agent.id,
        operational_supervisor.id,
    }
    assert administrator.id not in eligible_ids


def test_inactive_elevated_user_has_no_mutating_permissions(basic_world):
    user = _user(groups=["ops-supervisors"], active=False)
    status = Status.objects.get(domain="operational", code="new")
    ticket = Ticket.objects.create(
        number="OP-202607-900002",
        domain="operational",
        title="Inactive permissions",
        status=status,
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_reassign(user) is False
    assert can_change_confidentiality(user) is False
    assert can_update_work_state(user, ticket) is False


@pytest.mark.parametrize("role_key", DESIGNATION_KEYS)
def test_each_exact_scope_designation_can_action_but_cannot_assign(
    basic_world,
    role_key,
):
    user = _user(groups=[])
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_key.replace("-", " ").title(),
        scopes=[
            {
                "domain": "operational",
                "office": str(basic_world["office"].id),
                "service": str(basic_world["gen_info"].id),
            }
        ],
    )
    UserRole.objects.create(user=user, role=role, office=basic_world["office"])
    status = Status.objects.get(domain="operational", code="new")
    ticket = Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 900100:06d}",
        domain="operational",
        title="Designation permissions",
        status=status,
        channel="internal",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
    )

    assert can_update_work_state(user, ticket) is True
    assert can_add_ticket_content(user, ticket) is True
    assert can_assign(user, ticket=ticket) is False
    assert can_reassign(user, ticket=ticket) is False


@pytest.mark.parametrize(
    ("role_key", "domain"),
    [
        ("supervisor-operational", "operational"),
        ("lead-it", "it"),
    ],
)
def test_persisted_leadership_role_can_assign_without_keycloak_groups(
    basic_world,
    role_key,
    domain,
):
    user = _user(groups=[])
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_key,
        scopes=[{"domain": domain}],
    )
    UserRole.objects.create(user=user, role=role)
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    ticket = Ticket.objects.create(
        number=f"{'OP' if domain == 'operational' else 'IT'}-202607-900300",
        domain=domain,
        title="Persisted assignment authority",
        status=Status.objects.get(domain=domain, code="new"),
        channel="internal",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )

    assert can_assign(user, ticket=ticket) is True
    assert can_reassign(user, ticket=ticket) is True
