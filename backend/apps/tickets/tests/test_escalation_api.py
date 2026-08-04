from __future__ import annotations

from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.identity_access.models import Role, User, UserRole
from apps.tickets.models import Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db

CORRELATION_ID = "escalation-supervisor-search-test"


def _scoped_actor(basic_world, *, role_key: str) -> User:
    user = User.objects.create(
        username=f"staff-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        display_name=role_key.replace("-", " ").title(),
        is_active=True,
    )
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_key.replace("-", " ").title(),
        scopes=[
            {
                "domain": Ticket.Domain.OPERATIONAL,
                "office": str(basic_world["office"].id),
                "service": str(basic_world["gen_info"].id),
            }
        ],
    )
    UserRole.objects.create(user=user, role=role, office=basic_world["office"])
    return user


def _ticket(basic_world, *, status_code: str) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 960001:06d}",
        domain=Ticket.Domain.OPERATIONAL,
        title="Escalation supervisor API contract",
        status=Status.objects.get(domain=Ticket.Domain.OPERATIONAL, code=status_code),
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url(ticket: Ticket) -> str:
    return reverse("tickets-escalation-supervisors", args=[ticket.number])


def _transition_url(ticket: Ticket) -> str:
    return reverse("tickets-transition", args=[ticket.number])


def test_escalation_supervisor_endpoint_returns_only_safe_eligible_candidates(
    basic_world,
):
    actor = _scoped_actor(basic_world, role_key="examiner")
    ticket = _ticket(basic_world, status_code="in_progress")
    supervisor = _scoped_actor(basic_world, role_key="assistant-master")

    response = _client(actor).get(_url(ticket))

    assert response.status_code == 200
    assert response.data == {
        "results": [
            {
                "id": str(supervisor.id),
                "username": supervisor.username,
                "display_name": supervisor.display_name,
                "designations": ["Assistant Master"],
                "team_labels": ["Office Leadership"],
                "role_summaries": [
                    "Supervise reviews; validate recommendations; authorise "
                    "workflow progress. Authority: Approve within delegated authority."
                ],
            }
        ]
    }


def test_escalation_supervisor_endpoint_searches_deterministically(basic_world):
    actor = _scoped_actor(basic_world, role_key="examiner")
    ticket = _ticket(basic_world, status_code="in_progress")
    assistant = _scoped_actor(basic_world, role_key="assistant-master")
    assistant.display_name = "Amina Supervisor"
    assistant.save(update_fields=["display_name"])
    deputy = _scoped_actor(basic_world, role_key="deputy-master")
    deputy.display_name = "Zola Supervisor"
    deputy.save(update_fields=["display_name"])

    response = _client(actor).get(_url(ticket), {"search": "master"})

    assert response.status_code == 200
    assert [item["id"] for item in response.data["results"]] == [
        str(assistant.id),
        str(deputy.id),
    ]


def test_escalation_supervisor_endpoint_rejects_search_over_one_hundred_characters(
    basic_world,
):
    actor = _scoped_actor(basic_world, role_key="examiner")
    ticket = _ticket(basic_world, status_code="in_progress")

    response = _client(actor).get(
        _url(ticket),
        {"search": "x" * 101},
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_assignee_search"
    assert response.data["detail"] == "Supervisor search is invalid."
    assert set(response.data["fields"]) == {"search"}
    assert response.data["correlation_id"] == CORRELATION_ID


def test_escalation_supervisor_endpoint_forbids_actor_who_cannot_escalate(
    basic_world,
):
    actor = _scoped_actor(basic_world, role_key="examiner")
    ticket = _ticket(basic_world, status_code="escalated")

    response = _client(actor).get(_url(ticket))

    assert response.status_code == 403
    assert response.data["code"] == "ticket_action_forbidden"
    assert response.data["detail"] == "You cannot perform this ticket action."
    assert response.data["fields"] == {}


def test_escalation_transition_api_assigns_submitted_supervisor(basic_world):
    actor = _scoped_actor(basic_world, role_key="examiner")
    supervisor = _scoped_actor(basic_world, role_key="assistant-master")
    ticket = _ticket(basic_world, status_code="in_progress")

    response = _client(actor).post(
        _transition_url(ticket),
        {
            "to_status": "escalated",
            "updated_at": ticket.updated_at.isoformat(),
            "reason": "Requires delegated approval",
            "supervisor_id": str(supervisor.id),
        },
        format="json",
    )

    assert response.status_code == 200
    ticket.refresh_from_db()
    assert ticket.status.code == "escalated"
    assert ticket.assignee_id == supervisor.id
