from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth.models import Group

from apps.identity_access.models import User
from apps.tickets.models import Ticket
from apps.tickets.permissions import (
    can_change_confidentiality,
    can_reassign,
    eligible_assignee_queryset,
    user_groups,
)
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


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
        administrator.id,
    }
