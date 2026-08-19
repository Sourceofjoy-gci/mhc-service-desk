"""Custody assertions for authenticated staff-assisted public intake."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.catalogue.models import RequestType
from apps.identity_access.models import Role, User, UserRole
from apps.organisations.models import ServiceLocation
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def _intake_payload(basic_world: dict[str, object]) -> dict[str, object]:
    request_type = RequestType.objects.get(
        service=basic_world["gen_info"],
        code="HOURS",
    )
    return {
        "requester_name": "Assisted requester",
        "requester_email": "assisted@example.test",
        "title": "Staff-assisted intake",
        "description": "A staff member entered this request.",
        "service_code": request_type.service.code,
        "request_type_code": request_type.code,
        "office_code": basic_world["office"].code,
        "channel": "call",
        "consent": True,
    }


def _post_intake(client: APIClient, basic_world: dict[str, object]):
    return client.post(
        reverse("tickets-public-intake"),
        _intake_payload(basic_world),
        format="json",
        secure=True,
    )


def test_authenticated_staff_assisted_intake_records_the_staff_custody_actor(
    basic_world,
) -> None:
    staff = User.objects.create(
        username="intake-staff",
        display_name="Intake Staff",
        keycloak_subject="intake-staff-subject",
        keycloak_groups=["ops-agents"],
        office=basic_world["office"],
    )
    client = APIClient()
    client.force_authenticate(staff)

    response = _post_intake(client, basic_world)

    assert response.status_code == 201
    ticket = Ticket.objects.get(number=response.data["ticket_number"])
    audit = AuditEvent.objects.get(object_id=str(ticket.id), action="ticket.created")
    assert audit.actor_subject == "intake-staff-subject"
    event = ticket.custody_events.get()
    assert event.actor_kind == "user"
    assert event.actor_subject == "intake-staff-subject"
    assert event.actor_display_name == "Intake Staff"


@pytest.mark.parametrize("groups", [[], ["it-agents"]])
def test_staff_intake_rejects_roleless_and_wrong_domain_users(basic_world, groups) -> None:
    staff = User.objects.create(
        username=f"intake-denied-{'-'.join(groups) or 'roleless'}",
        keycloak_subject="intake-denied-subject",
        keycloak_groups=groups,
        office=basic_world["office"],
    )
    client = APIClient()
    client.force_authenticate(staff)

    response = _post_intake(client, basic_world)

    assert response.status_code == 403
    assert Ticket.objects.filter(title="Staff-assisted intake").count() == 0


def test_staff_intake_rejects_queue_constrained_authority(basic_world) -> None:
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Queue-only intake authority",
    )
    staff = User.objects.create(
        username="queue-constrained-intake",
        keycloak_subject="queue-constrained-subject",
        office=basic_world["office"],
    )
    role = Role.objects.create(
        keycloak_role=f"queue-intake-{uuid4().hex}",
        name="Queue-constrained intake staff",
        scopes=[
            {
                "domain": "operational",
                "office": str(basic_world["office"].id),
                "service": str(basic_world["gen_info"].id),
                "queue": str(queue.id),
            }
        ],
    )
    UserRole.objects.create(user=staff, role=role, office=basic_world["office"])
    client = APIClient()
    client.force_authenticate(staff)

    response = _post_intake(client, basic_world)

    assert response.status_code == 403
    assert Ticket.objects.filter(title="Staff-assisted intake").count() == 0
