"""Regression tests for ticket mutation and API integrity boundaries."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.organisations.models import Office
from apps.tickets import services
from apps.tickets.models import OutboxEvent, Ticket, TicketMessage, TicketNote
from apps.tickets.problem_change import ChangeManager, ProblemManager
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _user(groups: list[str], *, active: bool = True) -> User:
    user = User.objects.create(
        username=f"integrity-{uuid4().hex}",
        keycloak_subject=f"integrity-subject-{uuid4().hex}",
        keycloak_groups=groups,
        is_active=active,
    )
    user._groups = groups
    return user


def _ticket(
    basic_world,
    *,
    confidentiality: str = Ticket.Confidentiality.NORMAL,
) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 970001:06d}",
        domain=Ticket.Domain.OPERATIONAL,
        title="Integrity boundary",
        status=Status.objects.get(domain="operational", code="new"),
        channel=Ticket.Channel.WEB,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(code="HOURS"),
        office=basic_world["office"],
        confidentiality=confidentiality,
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_ticket_detail_rejects_inherited_base_mutations_with_405(
    basic_world,
    method: str,
) -> None:
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = getattr(_client(actor), method)(
        reverse("tickets-detail", args=[ticket.number]),
        {"title": "Lifecycle bypass"},
        format="json",
    )

    assert response.status_code == 405
    ticket.refresh_from_db()
    assert ticket.title == "Integrity boundary"


def test_ticket_collection_still_advertises_explicit_create_route(basic_world) -> None:
    response = _client(_user(["ops-agents"])).options(reverse("tickets-list"))

    assert response.status_code == 200
    assert "POST" in response.headers["Allow"]


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {
            "team": "",
            "waiting_reason": "",
            "blocked_reason": "",
            "next_action": "",
            "next_action_at": None,
        },
        {
            "assignee": None,
            "confidentiality": Ticket.Confidentiality.NORMAL,
        },
    ],
)
def test_empty_or_unchanged_work_state_is_a_true_no_op(
    basic_world,
    changes: dict[str, object],
) -> None:
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    updated = services.update_work_state(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        changes=changes,
    )

    assert updated.updated_at == previous_updated_at
    ticket.refresh_from_db()
    assert ticket.updated_at == previous_updated_at
    assert not AuditEvent.objects.filter(
        object_id=str(ticket.id),
        action="ticket.work_state.changed",
    ).exists()
    assert not OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id),
        event_type="ticket.work_state.changed",
    ).exists()


def test_empty_work_state_patch_returns_unchanged_representation(basic_world) -> None:
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    response = _client(actor).patch(
        reverse("tickets-work-state", args=[ticket.number]),
        {"updated_at": ticket.updated_at.isoformat()},
        format="json",
    )

    assert response.status_code == 200
    assert parse_datetime(response.data["updated_at"]) == previous_updated_at
    ticket.refresh_from_db()
    assert ticket.updated_at == previous_updated_at
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


def test_work_state_revalidates_canonical_scope_when_ticket_moves_after_read(
    basic_world,
) -> None:
    actor = _user(["ops-agents"])
    role = Role.objects.create(
        keycloak_role="agent-operational",
        name="Office-scoped operational agent",
        scopes=[],
    )
    UserRole.objects.create(user=actor, role=role, office=basic_world["office"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="INT-OTHER",
        name="Other integrity office",
    )
    Ticket.objects.filter(id=ticket.id).update(office=other_office)

    with pytest.raises(services.TicketScopeError):
        services.update_work_state(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=previous_updated_at,
            changes={"team": "Must not cross scope"},
        )

    ticket.refresh_from_db()
    assert ticket.office == other_office
    assert ticket.team == ""
    assert ticket.updated_at == previous_updated_at
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


@pytest.mark.parametrize(
    ("groups", "active", "confidentiality", "allowed"),
    [
        (["ops-agents"], True, Ticket.Confidentiality.NORMAL, True),
        (["ops-supervisors"], True, Ticket.Confidentiality.NORMAL, True),
        (["system-admins"], True, Ticket.Confidentiality.NORMAL, True),
        (["auditors"], True, Ticket.Confidentiality.NORMAL, False),
        (["ops-agents"], False, Ticket.Confidentiality.NORMAL, False),
        (["security-responders"], True, Ticket.Confidentiality.RESTRICTED, False),
    ],
)
def test_detail_exposes_authoritative_content_mutation_capabilities(
    basic_world,
    groups: list[str],
    active: bool,
    confidentiality: str,
    allowed: bool,
) -> None:
    actor = _user(groups, active=active)
    ticket = _ticket(basic_world, confidentiality=confidentiality)

    response = _client(actor).get(reverse("tickets-detail", args=[ticket.number]))

    assert response.status_code == 200
    capabilities = response.data["capabilities"]
    assert capabilities["can_add_message"] is allowed
    assert capabilities["can_add_note"] is allowed
    assert capabilities["can_upload_attachment"] is allowed


@pytest.mark.parametrize(
    ("groups", "active", "confidentiality", "route_name", "payload", "model"),
    [
        (
            ["ops-agents"],
            False,
            Ticket.Confidentiality.NORMAL,
            "tickets-messages",
            {"body_text": "inactive mutation"},
            TicketMessage,
        ),
        (
            ["security-responders"],
            True,
            Ticket.Confidentiality.RESTRICTED,
            "tickets-notes",
            {"body": "read-only responder mutation"},
            TicketNote,
        ),
    ],
)
def test_no_mutation_actor_cannot_add_ticket_content(
    basic_world,
    groups: list[str],
    active: bool,
    confidentiality: str,
    route_name: str,
    payload: dict[str, str],
    model: type[TicketMessage] | type[TicketNote],
) -> None:
    actor = _user(groups, active=active)
    ticket = _ticket(basic_world, confidentiality=confidentiality)

    response = _client(actor).post(
        reverse(route_name, args=[ticket.number]),
        payload,
        format="json",
    )

    assert response.status_code == 403
    assert not model.objects.filter(ticket=ticket).exists()
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


@pytest.mark.parametrize(
    ("open_record", "expected_tags", "expected_custom_fields"),
    [
        (
            lambda: ProblemManager.open_problem(
                title="Repeated outage",
                description="Investigate recurrence",
                opened_by="problem-manager",
            ),
            ["problem"],
            {},
        ),
        (
            lambda: ChangeManager.open_change(
                title="Upgrade network",
                description="Apply the approved maintenance release",
                scheduled_at=datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
                risk="medium",
                opened_by="change-manager",
            ),
            ["change", "risk:medium"],
            {
                "scheduled_at": "2026-08-01T20:00:00+00:00",
                "risk": "medium",
            },
        ),
    ],
)
def test_problem_and_change_configuration_is_part_of_canonical_creation_event(
    basic_world,
    open_record: Callable[[], Ticket],
    expected_tags: list[str],
    expected_custom_fields: dict[str, str],
) -> None:
    ticket = open_record()

    audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.created",
    )
    outbox = OutboxEvent.objects.get(
        aggregate_id=str(ticket.id),
        event_type="ticket.created",
    )
    assert ticket.tags == expected_tags
    assert ticket.custom_fields == expected_custom_fields
    assert audit.payload == outbox.payload
    assert audit.payload["after"]["tags"] == expected_tags
    if expected_custom_fields:
        assert audit.payload["after"]["custom_fields"] == expected_custom_fields
    else:
        assert "custom_fields" not in audit.payload["after"]
