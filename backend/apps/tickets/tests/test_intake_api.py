"""Custody assertions for authenticated staff-assisted public intake."""
from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalogue.models import RequestType
from apps.identity_access.models import User
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def test_authenticated_staff_assisted_intake_records_the_staff_custody_actor(
    basic_world,
) -> None:
    staff = User.objects.create(
        username="intake-staff",
        display_name="Intake Staff",
        keycloak_subject="intake-staff-subject",
    )
    request_type = RequestType.objects.get(
        service=basic_world["gen_info"], code="HOURS"
    )
    client = APIClient()
    client.force_authenticate(staff)

    response = client.post(
        reverse("tickets-public-intake"),
        {
            "requester_name": "Assisted requester",
            "requester_email": "assisted@example.test",
            "title": "Staff-assisted intake",
            "description": "A staff member entered this request.",
            "service_code": request_type.service.code,
            "request_type_code": request_type.code,
            "office_code": basic_world["office"].code,
            "channel": "call",
            "consent": True,
        },
        format="json",
        secure=True,
    )

    assert response.status_code == 201
    ticket = Ticket.objects.get(number=response.data["ticket_number"])
    event = ticket.custody_events.get()
    assert event.actor_kind == "user"
    assert event.actor_subject == "intake-staff-subject"
    assert event.actor_display_name == "Intake Staff"
