from typing import Never
from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.identity_access.models import User
from apps.integrations import views
from apps.organisations.models import Office
from apps.tickets.models import OutboxEvent, Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


class _DeniedProvider:
    def get(self, _key: object, _default: object = None) -> Never:
        raise AssertionError("matter provider was queried before ticket access was granted")


def _user(groups: list[str]) -> User:
    # Operational and IT authority is confined to the officer's office, so
    # every staff actor is based at the seeded ``basic_world`` office.
    user = User.objects.create(
        username=f"matter-user-{uuid4().hex}",
        keycloak_subject=f"matter-subject-{uuid4().hex}",
        office=Office.objects.get(code="TST-1"),
    )
    vars(user)["_groups"] = list(groups)
    return user


def _ticket(
    basic_world: dict[str, object],
    *,
    domain: str = "operational",
    confidentiality: str = "normal",
) -> Ticket:
    service_key = "gen_info" if domain == "operational" else "it_inc"
    service = basic_world[service_key]
    return Ticket.objects.create(
        number="OP-202607-910001" if domain == "operational" else "IT-202607-910001",
        domain=domain,
        title="Validate matter scope",
        status=Status.objects.get(domain=domain, code="new"),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        confidentiality=confidentiality,
        matter_reference="EST-2026-000123",
    )


@pytest.mark.parametrize(
    ("groups", "domain", "confidentiality"),
    [
        ([], "operational", "normal"),
        (["it-agents"], "operational", "normal"),
        (["ops-agents"], "operational", "restricted"),
    ],
    ids=["no-scope", "cross-domain", "restricted"],
)
def test_validate_matter_hides_denied_tickets_without_provider_or_outbox_side_effects(
    basic_world,
    monkeypatch,
    groups: list[str],
    domain: str,
    confidentiality: str,
):
    ticket = _ticket(
        basic_world,
        domain=domain,
        confidentiality=confidentiality,
    )
    monkeypatch.setattr(views, "_FAKE_ESTATES", _DeniedProvider())
    client = APIClient()
    client.force_authenticate(user=_user(groups))

    response = client.get(reverse("validate-matter", args=[ticket.number]))

    assert response.status_code == 404
    assert response.data == {"detail": "ticket not found"}
    assert not OutboxEvent.objects.exists()


def test_validate_matter_allows_a_scoped_restricted_ticket_and_records_validation(
    basic_world,
):
    ticket = _ticket(basic_world, confidentiality="restricted")
    client = APIClient()
    client.force_authenticate(user=_user(["ops-supervisors"]))

    response = client.get(reverse("validate-matter", args=[ticket.number]))

    assert response.status_code == 200
    assert response.data["status"] == "found"
    assert response.data["ticket"] == ticket.number
    assert response.data["reference"] == "EST-2026-000123"
    assert response.data["summary"] == {
        "matter_number": "EST-2026-000123",
        "deceased_initial": "D.",
        "estate_type": "testate",
        "status": "letters_of_executorship_issued",
        "office": "MHC-MBA",
        "updated_at": "2026-05-30T11:30:00Z",
    }
    event = OutboxEvent.objects.get(
        aggregate="ticket",
        aggregate_id=str(ticket.id),
        event_type="eestate.validated",
    )
    assert event.payload == {
        "matter_number": "EST-2026-000123",
        "by": response.wsgi_request.user.keycloak_subject,
    }


def test_validate_matter_rejects_an_inactive_user_before_provider_or_outbox_access(
    basic_world,
    monkeypatch,
):
    ticket = _ticket(basic_world)
    user = _user(["ops-agents"])
    user.is_active = False
    user.save(update_fields=["is_active"])
    monkeypatch.setattr(views, "_FAKE_ESTATES", _DeniedProvider())
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(reverse("validate-matter", args=[ticket.number]))

    assert response.status_code == 404
    assert response.data == {"detail": "ticket not found"}
    assert not OutboxEvent.objects.exists()
