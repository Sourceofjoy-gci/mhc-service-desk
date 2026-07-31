"""Django-admin regressions for ticket allocation and lifecycle custody."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.identity_access.models import User
from apps.organisations.models import ServiceLocation
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


CONTROLLED_FIELDS = {
    "domain",
    "status",
    "priority",
    "channel",
    "service",
    "request_type",
    "office",
    "queue",
    "assignee",
    "team",
    "confidentiality",
    "waiting_reason",
    "blocked_reason",
    "next_action",
    "next_action_at",
    "resolution_code",
    "resolution_summary",
    "acknowledged_at",
    "first_responded_at",
    "resolved_at",
    "closed_at",
    "reopened_at",
}


def _admin_user() -> User:
    return User.objects.create(
        username=f"ticket-admin-{uuid4().hex}",
        keycloak_subject=f"ticket-admin-subject-{uuid4().hex}",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )


def _ticket(basic_world, *, queue: ServiceLocation) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-ADMIN-{uuid4().hex[:12]}",
        domain=Ticket.Domain.OPERATIONAL,
        title="Admin custody boundary",
        description="Original description",
        status=Status.objects.get(domain=Ticket.Domain.OPERATIONAL, code="new"),
        priority=Ticket.Priority.P3,
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        queue=queue,
    )


def _evidence_counts(ticket: Ticket) -> tuple[int, int, int]:
    return (
        AuditEvent.objects.filter(object_id=str(ticket.id)).count(),
        OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count(),
        TicketCustodyEvent.objects.filter(ticket=ticket).count(),
    )


def test_ticket_admin_form_excludes_allocation_and_lifecycle_controlled_fields(
    client,
    basic_world,
) -> None:
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Admin form queue",
    )
    ticket = _ticket(basic_world, queue=queue)
    client.force_login(_admin_user())

    response = client.get(
        reverse("admin:tickets_ticket_change", args=[ticket.pk]),
        secure=True,
    )

    assert response.status_code == 200
    assert CONTROLLED_FIELDS.isdisjoint(response.context["adminform"].form.fields)
    assert CONTROLLED_FIELDS <= set(response.context["adminform"].readonly_fields)


def test_ticket_admin_post_cannot_forge_owner_queue_or_lifecycle_changes(
    client,
    basic_world,
) -> None:
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Current admin queue",
    )
    forged_queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Inactive forged queue",
        is_active=False,
    )
    forged_assignee = User.objects.create(
        username=f"inactive-assignee-{uuid4().hex}",
        keycloak_subject=f"inactive-assignee-subject-{uuid4().hex}",
        is_active=False,
    )
    forged_status = Status.objects.get(
        domain=Ticket.Domain.OPERATIONAL,
        code="closed",
    )
    ticket = _ticket(basic_world, queue=queue)
    previous_updated_at = ticket.updated_at
    previous_evidence = _evidence_counts(ticket)
    client.force_login(_admin_user())

    response = client.post(
        reverse("admin:tickets_ticket_change", args=[ticket.pk]),
        {
            "number": ticket.number,
            "title": "Permitted metadata correction",
            "description": ticket.description,
            "source_account": "",
            "requester": str(ticket.requester_id),
            "organisation": "",
            "legal_hold_reason": "",
            "matter_reference": "",
            "external_message_id": "",
            "tags": "[]",
            "custom_fields": "{}",
            "domain": Ticket.Domain.IT,
            "status": str(forged_status.id),
            "priority": Ticket.Priority.P1,
            "channel": Ticket.Channel.WEB,
            "service": str(ticket.service_id),
            "request_type": str(ticket.request_type_id),
            "office": str(ticket.office_id),
            "queue": str(forged_queue.id),
            "assignee": str(forged_assignee.id),
            "team": "Forged team",
            "confidentiality": Ticket.Confidentiality.RESTRICTED,
            "waiting_reason": "forged",
            "blocked_reason": "forged",
            "next_action": "forged",
            "resolution_code": "forged",
            "resolution_summary": "forged",
            "_save": "Save",
        },
        secure=True,
    )

    assert response.status_code == 302
    ticket.refresh_from_db()
    assert ticket.title == "Permitted metadata correction"
    assert ticket.domain == Ticket.Domain.OPERATIONAL
    assert ticket.status_id != forged_status.id
    assert ticket.priority == Ticket.Priority.P3
    assert ticket.channel == Ticket.Channel.INTERNAL
    assert ticket.queue_id == queue.id
    assert ticket.assignee_id is None
    assert ticket.team == ""
    assert ticket.confidentiality == Ticket.Confidentiality.NORMAL
    assert ticket.waiting_reason == ""
    assert ticket.blocked_reason == ""
    assert ticket.next_action == ""
    assert ticket.resolution_code == ""
    assert ticket.resolution_summary == ""
    assert ticket.updated_at > previous_updated_at
    assert _evidence_counts(ticket) == previous_evidence


def test_ticket_admin_disables_direct_creation_and_deletion(client, basic_world) -> None:
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Retained admin queue",
    )
    ticket = _ticket(basic_world, queue=queue)
    client.force_login(_admin_user())

    assert client.get(reverse("admin:tickets_ticket_add"), secure=True).status_code == 403
    delete_url = reverse("admin:tickets_ticket_delete", args=[ticket.pk])
    assert client.get(delete_url, secure=True).status_code == 403
    assert client.post(delete_url, {"post": "yes"}, secure=True).status_code == 403
    assert Ticket.objects.filter(pk=ticket.pk).exists()
