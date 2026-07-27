from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.identity_access.models import Role, User, UserRole
from apps.tickets.api import TicketDetailSerializer, TicketListSerializer
from apps.tickets.models import Ticket
from apps.tickets.workflow import available_transitions
from apps.workflow.models import Status, Transition

pytestmark = pytest.mark.django_db


def _user(groups: list[str]) -> User:
    user = User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        keycloak_groups=groups,
    )
    user._groups = groups
    return user


def _ticket(basic_world, *, domain: str = "operational", status_code: str = "new"):
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    prefix = "OP" if domain == "operational" else "IT"
    return Ticket.objects.create(
        number=f"{prefix}-202607-{Ticket.objects.count() + 930001:06d}",
        domain=domain,
        title="Workflow capability",
        status=Status.objects.get(domain=domain, code=status_code),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _context(user: User):
    return {"request": SimpleNamespace(user=user)}


@pytest.mark.parametrize("domain", ["operational", "it"])
def test_available_transitions_only_returns_active_moves_from_current_status(
    basic_world,
    domain,
):
    actor = _user(["ops-agents"] if domain == "operational" else ["it-agents"])
    ticket = _ticket(basic_world, domain=domain)
    expected = Transition.objects.get(
        domain=domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    Transition.objects.filter(domain=domain).exclude(id=expected.id).update(is_active=False)

    result = available_transitions(ticket, actor)

    assert list(result) == [expected]
    expected.is_active = False
    expected.save(update_fields=["is_active"])
    assert not available_transitions(ticket, actor).exists()


def test_required_role_hides_transition_but_administrators_bypass_it(basic_world):
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-supervisors"
    transition.save(update_fields=["required_role"])

    assert not available_transitions(ticket, _user(["ops-agents"])).exists()
    assert available_transitions(ticket, _user(["ops-supervisors"])).get() == transition
    assert available_transitions(ticket, _user(["system-admins"])).get() == transition


def test_persisted_auditor_has_no_transitions_despite_mutable_group_snapshot(basic_world):
    ticket = _ticket(basic_world)
    actor = _user(["ops-supervisors"])
    role = Role.objects.create(keycloak_role="auditors", name="Auditor")
    UserRole.objects.create(user=actor, role=role)

    assert not available_transitions(ticket, actor).exists()


@pytest.mark.parametrize(
    ("groups", "active"),
    [(["auditors"], True), (["it-agents"], True), (["ops-agents"], False)],
)
def test_read_only_cross_domain_and_inactive_actors_have_no_transitions(
    basic_world,
    groups,
    active,
):
    ticket = _ticket(basic_world)
    actor = _user(groups)
    actor.is_active = active
    actor.save(update_fields=["is_active"])

    assert not available_transitions(ticket, actor).exists()


def test_detail_serializes_resolution_requirements_and_list_serializes_codes(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world, status_code="in_progress")
    Transition.objects.filter(
        domain=ticket.domain,
        from_status=ticket.status,
    ).exclude(to_status__code="resolved").update(is_active=False)

    detail = TicketDetailSerializer(ticket, context=_context(actor)).data
    listing = TicketListSerializer(ticket, context=_context(actor)).data

    assert detail["available_transitions"] == [
        {
            "to_status": "resolved",
            "label": "Resolve",
            "requires_resolution": True,
            "requires_reason": False,
        },
    ]
    assert listing["available_transition_codes"] == [
        item["to_status"] for item in detail["available_transitions"]
    ]


def test_required_fields_reason_is_exposed_as_requirement(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_fields = ["reason"]
    transition.save(update_fields=["required_fields"])

    detail = TicketDetailSerializer(ticket, context=_context(actor)).data

    assert detail["available_transitions"] == [
        {
            "to_status": "triage",
            "label": "Begin triage",
            "requires_resolution": False,
            "requires_reason": True,
        }
    ]
