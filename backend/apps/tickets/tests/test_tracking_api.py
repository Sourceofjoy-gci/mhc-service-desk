from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.urls import reverse
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.identity_access.models import User
from apps.tickets import services


@pytest.fixture
def tracking_world(basic_world):
    actor = User.objects.create(
        username="tracking-agent",
        keycloak_subject="tracking-agent-subject",
        keycloak_groups=["ops-agents"],
    )
    actor._groups = ["ops-agents"]
    ops_client = APIClient()
    ops_client.force_authenticate(actor)
    ops_ticket = services.create_ticket(
        domain="operational",
        title="Estate status enquiry",
        description="Requester-private description",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
        channel="call",
        actor=actor,
        actor_subject=actor.keycloak_subject,
    )
    it_ticket = services.create_ticket(
        domain="it",
        title="Internal IT issue",
        description="Internal details",
        requester=basic_world["contact"],
        service=basic_world["it_inc"],
        request_type=basic_world["it_inc"].request_types.get(),
        office=basic_world["office"],
        channel="internal",
    )
    return SimpleNamespace(
        actor=actor,
        ops_client=ops_client,
        ops_ticket=ops_ticket,
        it_ticket=it_ticket,
    )


def test_tracking_returns_only_requester_safe_progress_for_an_in_scope_reference(
    tracking_world,
):
    world = tracking_world
    render_datetime = serializers.DateTimeField().to_representation
    created_event = world.ops_ticket.custody_events.get()

    response = world.ops_client.get(
        reverse("tickets-tracking"),
        {"reference": f"  {world.ops_ticket.number.lower()}  "},
    )

    assert response.status_code == 200
    assert response.data == {
        "reference": world.ops_ticket.number,
        "title": world.ops_ticket.title,
        "tracking_status": "Submitted",
        "status_updated_at": render_datetime(created_event.occurred_at),
        "created_at": render_datetime(world.ops_ticket.created_at),
        "updated_at": render_datetime(world.ops_ticket.updated_at),
        "office": world.ops_ticket.office.name,
        "service": world.ops_ticket.service.name,
        "progress": [
            {
                "status": "Submitted",
                "occurred_at": render_datetime(created_event.occurred_at),
            }
        ],
    }
    assert "requester" not in response.data
    assert "notes" not in response.data
    assert "actor" not in response.data["progress"][0]


def test_tracking_requires_authentication(tracking_world):
    response = APIClient().get(
        reverse("tickets-tracking"),
        {"reference": tracking_world.ops_ticket.number},
    )

    assert response.status_code == 401


def test_tracking_rejects_a_malformed_reference(tracking_world):
    response = tracking_world.ops_client.get(
        reverse("tickets-tracking"),
        {"reference": "not a ticket"},
        HTTP_X_CORRELATION_ID="tracking-invalid",
    )

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid_ticket_reference",
        "detail": "Enter a valid ticket reference.",
        "fields": {"reference": ["Enter a valid ticket reference."]},
        "correlation_id": "tracking-invalid",
    }


def test_tracking_rejects_the_legacy_long_reference_shape(tracking_world):
    response = tracking_world.ops_client.get(
        reverse("tickets-tracking"),
        {"reference": "OP-202608-000123"},
    )

    assert response.status_code == 400


def test_tracking_rejects_non_ascii_digits(tracking_world):
    response = tracking_world.ops_client.get(
        reverse("tickets-tracking"),
        {"reference": "O１２３４５"},
    )

    assert response.status_code == 400


def test_ticket_detail_routes_accept_new_and_immutable_legacy_references():
    assert reverse("tickets-detail", kwargs={"number": "O00001"}).endswith(
        "/tickets/O00001/"
    )
    assert reverse(
        "tickets-detail",
        kwargs={"number": "OP-202608-000123"},
    ).endswith("/tickets/OP-202608-000123/")


def test_nonexistent_and_out_of_scope_references_are_indistinguishable(
    tracking_world,
):
    headers = {"HTTP_X_CORRELATION_ID": "tracking-hidden"}
    nonexistent = tracking_world.ops_client.get(
        reverse("tickets-tracking"),
        {"reference": "O99999"},
        **headers,
    )
    out_of_scope = tracking_world.ops_client.get(
        reverse("tickets-tracking"),
        {"reference": tracking_world.it_ticket.number},
        **headers,
    )

    assert nonexistent.status_code == out_of_scope.status_code == 404
    assert nonexistent.data == out_of_scope.data
    assert nonexistent.data == {
        "code": "not_found",
        "detail": "Ticket not found.",
        "fields": {},
        "correlation_id": "tracking-hidden",
    }
