from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.tickets.models import OutboxEvent, Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db

CORRELATION_ID = "work-state-test-correlation"


def _user(groups: list[str], *, display_name: str = "") -> User:
    user = User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        display_name=display_name,
        keycloak_groups=groups,
    )
    user._groups = groups
    return user


def _ticket(basic_world, *, domain: str = "operational", confidentiality="normal") -> Ticket:
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    prefix = "OP" if domain == "operational" else "IT"
    return Ticket.objects.create(
        number=f"{prefix}-202607-{Ticket.objects.count() + 920001:06d}",
        domain=domain,
        title="Endpoint work state",
        description="Ticket detail",
        status=Status.objects.get(domain=domain, code="new"),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        confidentiality=confidentiality,
    )


def _client(user: User | None = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _grant_persisted_auditor(user: User) -> None:
    role = Role.objects.create(keycloak_role="auditors", name="Auditor")
    UserRole.objects.create(user=user, role=role)


def _patch(client: APIClient, ticket: Ticket, data: dict):
    return client.patch(
        reverse("tickets-work-state", args=[ticket.number]),
        data,
        format="json",
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )


def test_work_state_requires_authentication(basic_world):
    ticket = _ticket(basic_world)

    response = _patch(
        _client(),
        ticket,
        {"updated_at": ticket.updated_at.isoformat(), "team": "Operations"},
    )

    assert response.status_code == 401
    assert response.data["correlation_id"] == CORRELATION_ID


def test_work_state_hides_out_of_scope_ticket(basic_world):
    ticket = _ticket(basic_world, domain="operational")
    response = _patch(
        _client(_user(["it-agents"])),
        ticket,
        {"updated_at": ticket.updated_at.isoformat(), "team": "IT"},
    )

    assert response.status_code == 404
    assert response.data["code"] == "not_found"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"team": "Operations"}, "updated_at"),
        ({"updated_at": "not-a-date", "team": "Operations"}, "updated_at"),
        ({"updated_at": "2026-07-27T12:00:00Z", "team": ["not", "text"]}, "team"),
    ],
)
def test_work_state_validates_timestamp_and_field_types(basic_world, payload, field):
    ticket = _ticket(basic_world)

    response = _patch(_client(_user(["ops-agents"])), ticket, payload)

    assert response.status_code == 400
    assert response.data["code"] == "invalid_work_state"
    assert response.data["detail"] == "Work state is invalid."
    assert field in response.data["fields"]
    assert response.data["correlation_id"] == CORRELATION_ID


def test_work_state_returns_refreshed_ticket_detail(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = _patch(
        _client(actor),
        ticket,
        {
            "updated_at": ticket.updated_at.isoformat(),
            "assignee": str(actor.id),
            "team": "Operations",
            "next_action": "Call requester",
        },
    )

    assert response.status_code == 200
    assert response.data["number"] == ticket.number
    assert response.data["assignee"] == actor.id
    assert response.data["team"] == "Operations"
    assert response.data["next_action"] == "Call requester"
    assert response.data["updated_at"] != ticket.updated_at.isoformat()
    assert response.data["capabilities"]["can_self_assign"] is False


def test_work_state_returns_field_error_for_ineligible_target(basic_world):
    supervisor = _user(["ops-supervisors"])
    target = _user(["it-agents"])
    ticket = _ticket(basic_world)

    response = _patch(
        _client(supervisor),
        ticket,
        {"updated_at": ticket.updated_at.isoformat(), "assignee": str(target.id)},
    )

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid_work_state",
        "detail": "Work state is invalid.",
        "fields": {"assignee": ["Select a valid assignee."]},
        "correlation_id": CORRELATION_ID,
    }


def test_work_state_returns_stable_forbidden_error_for_role_denial(basic_world):
    actor = _user(["ops-agents"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = _patch(
        _client(actor),
        ticket,
        {"updated_at": ticket.updated_at.isoformat(), "assignee": str(target.id)},
    )

    assert response.status_code == 403
    assert response.data == {
        "code": "ticket_action_forbidden",
        "detail": "You cannot perform this ticket action.",
        "fields": {},
        "correlation_id": CORRELATION_ID,
    }


def test_work_state_returns_current_timestamp_for_stale_update(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    stale = ticket.updated_at - timedelta(microseconds=1)

    response = _patch(
        _client(actor),
        ticket,
        {"updated_at": stale.isoformat(), "team": "Operations"},
    )

    assert response.status_code == 409
    assert response.data["code"] == "stale_ticket"
    assert response.data["detail"] == "The ticket was updated by another user."
    assert set(response.data["fields"]) == {"updated_at"}
    current = parse_datetime(response.data["fields"]["updated_at"][0])
    assert current == ticket.updated_at
    assert current.microsecond == ticket.updated_at.microsecond
    assert response.data["correlation_id"] == CORRELATION_ID


def test_assignees_are_filtered_by_ticket_domain(basic_world):
    actor = _user(["ops-supervisors"], display_name="Supervisor")
    eligible = _user(["ops-agents"], display_name="Eligible Agent")
    administrator = _user(["system-admins"], display_name="Administrator")
    _user(["it-agents"], display_name="IT Only")
    _user(["auditors"], display_name="Auditor")
    inactive = _user(["ops-agents"], display_name="Inactive")
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    ticket = _ticket(basic_world)

    response = _client(actor).get(
        reverse("tickets-assignees", args=[ticket.number]),
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )

    assert response.status_code == 200
    assert response.data == {
        "results": [
            {
                "id": str(administrator.id),
                "username": administrator.username,
                "display_name": "Administrator",
            },
            {
                "id": str(eligible.id),
                "username": eligible.username,
                "display_name": "Eligible Agent",
            },
            {
                "id": str(actor.id),
                "username": actor.username,
                "display_name": "Supervisor",
            },
        ]
    }


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        (
            ["ops-agents"],
            {
                "can_update_work_state": True,
                "can_self_assign": True,
                "can_reassign": False,
                "can_change_confidentiality": False,
            },
        ),
        (
            ["ops-supervisors"],
            {
                "can_update_work_state": True,
                "can_self_assign": True,
                "can_reassign": True,
                "can_change_confidentiality": True,
            },
        ),
        (
            ["auditors"],
            {
                "can_update_work_state": False,
                "can_self_assign": False,
                "can_reassign": False,
                "can_change_confidentiality": False,
            },
        ),
    ],
)
def test_ticket_detail_exposes_request_derived_capabilities(basic_world, groups, expected):
    user = _user(groups)
    ticket = _ticket(basic_world)

    response = _client(user).get(reverse("tickets-detail", args=[ticket.number]))

    assert response.status_code == 200
    capabilities = response.data["capabilities"]
    assert {key: capabilities[key] for key in expected} == expected
    assert capabilities["self_assignee_id"] == (
        str(user.id) if expected["can_self_assign"] else None
    )


def test_capabilities_use_request_local_group_snapshot(basic_world):
    user = _user([])
    user._groups = ["ops-agents"]
    ticket = _ticket(basic_world)

    response = _client(user).get(reverse("tickets-detail", args=[ticket.number]))

    assert response.status_code == 200
    assert response.data["capabilities"]["can_update_work_state"] is True
    assert response.data["capabilities"]["can_self_assign"] is True
    assert response.data["capabilities"]["self_assignee_id"] == str(user.id)

    update = _patch(
        _client(user),
        ticket,
        {"updated_at": ticket.updated_at.isoformat(), "assignee": str(user.id)},
    )
    assert update.status_code == 200
    assert update.data["assignee"] == user.id


def test_persisted_auditor_has_no_mutation_capabilities(basic_world):
    user = _user(["ops-supervisors"])
    _grant_persisted_auditor(user)
    ticket = _ticket(basic_world)
    client = _client(user)

    detail = client.get(reverse("tickets-detail", args=[ticket.number]))

    assert detail.status_code == 200
    assert detail.data["capabilities"] == {
        "can_update_work_state": False,
        "can_self_assign": False,
        "self_assignee_id": None,
        "can_reassign": False,
        "can_change_confidentiality": False,
    }


def test_persisted_auditor_patch_is_forbidden_and_has_no_side_effects(basic_world):
    user = _user(["ops-supervisors"])
    _grant_persisted_auditor(user)
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    update = _patch(
        _client(user),
        ticket,
        {"updated_at": ticket.updated_at.isoformat(), "team": "Must not persist"},
    )

    assert update.status_code == 403
    assert update.data == {
        "code": "ticket_action_forbidden",
        "detail": "You cannot perform this ticket action.",
        "fields": {},
        "correlation_id": CORRELATION_ID,
    }
    ticket.refresh_from_db()
    assert ticket.team == ""
    assert ticket.updated_at == previous_updated_at
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


def test_inactive_elevated_user_has_no_mutating_capabilities(basic_world):
    user = _user(["ops-supervisors"])
    user.is_active = False
    user.save(update_fields=["is_active"])
    ticket = _ticket(basic_world)

    response = _client(user).get(reverse("tickets-detail", args=[ticket.number]))

    assert response.status_code == 200
    assert response.data["capabilities"] == {
        "can_update_work_state": False,
        "can_self_assign": False,
        "self_assignee_id": None,
        "can_reassign": False,
        "can_change_confidentiality": False,
    }
