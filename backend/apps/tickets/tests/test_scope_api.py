from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from apps.identity_access.models import User
from apps.tickets.models import Ticket
from apps.tickets.views import TicketViewSet
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


@pytest.fixture
def scoped_tickets(basic_world):
    tickets = {}
    for domain, confidentiality in (
        ("operational", "normal"),
        ("operational", "restricted"),
        ("it", "normal"),
        ("it", "restricted"),
    ):
        service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
        key = f"{domain}-{confidentiality}"
        prefix = "OP" if domain == "operational" else "IT"
        sequence = 1 if confidentiality == "normal" else 2
        tickets[key] = Ticket.objects.create(
            number=f"{prefix}-202607-{sequence:06d}",
            domain=domain,
            title=key,
            status=Status.objects.get(domain=domain, code="new"),
            priority="P3",
            channel="web",
            requester=basic_world["contact"],
            service=service,
            request_type=service.request_types.get(),
            office=basic_world["office"],
            confidentiality=confidentiality,
        )
    return tickets


def _user(groups):
    user = User.objects.create(
        username=f"user-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
    )
    user._groups = groups
    return user


def _list_titles(groups):
    request = APIRequestFactory().get("/api/v1/tickets/")
    force_authenticate(request, user=_user(groups))
    response = TicketViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 200
    return {row["title"] for row in response.data["results"]}


def test_security_responder_lists_only_restricted_tickets_and_cannot_retrieve_normal(
    scoped_tickets,
):
    assert _list_titles(["security-responders"]) == {
        "operational-restricted",
        "it-restricted",
    }

    normal = scoped_tickets["operational-normal"]
    request = APIRequestFactory().get(f"/api/v1/tickets/{normal.number}/")
    force_authenticate(request, user=_user(["security-responders"]))
    response = TicketViewSet.as_view({"get": "retrieve"})(request, number=normal.number)

    assert response.status_code == 404


def test_agent_lists_only_normal_tickets_in_its_domain(scoped_tickets):
    assert _list_titles(["ops-agents"]) == {"operational-normal"}


def test_supervisor_lists_normal_and_restricted_tickets_in_its_domain(scoped_tickets):
    assert _list_titles(["ops-supervisors"]) == {
        "operational-normal",
        "operational-restricted",
    }


@pytest.mark.parametrize(
    ("groups", "expected_open"),
    [
        (["ops-agents"], 1),
        (["ops-supervisors"], 2),
        (["auditors"], 2),
    ],
)
def test_routed_operational_dashboard_aggregates_only_scoped_tickets(
    groups,
    expected_open,
    scoped_tickets,
):
    client = APIClient()
    client.force_authenticate(user=_user(groups))

    response = client.get(reverse("tickets-dashboard-operational"))

    assert response.status_code == 200
    assert response.data["totals"]["open"] == expected_open
