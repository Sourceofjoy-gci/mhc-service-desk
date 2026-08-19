"""Queue lifecycle regressions for tickets with custody-bearing routing."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.models.deletion import PROTECT, SET_NULL, ProtectedError
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.identity_access.models import User
from apps.organisations.models import Office, ServiceLocation
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db(transaction=True)


def _admin_user() -> User:
    return User.objects.create(
        username=f"queue-admin-{uuid4().hex}",
        keycloak_subject=f"queue-admin-subject-{uuid4().hex}",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )


def _ticket(basic_world, *, queue: ServiceLocation) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-QUEUE-PROTECT-{uuid4().hex[:10]}",
        domain=Ticket.Domain.OPERATIONAL,
        title="Protected queue custody",
        status=Status.objects.get(domain=Ticket.Domain.OPERATIONAL, code="new"),
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


def test_referenced_queue_programmatic_delete_is_protected_without_custody_loss(
    basic_world,
) -> None:
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Programmatic protected queue",
    )
    ticket = _ticket(basic_world, queue=queue)
    before = _evidence_counts(ticket)

    with pytest.raises(ProtectedError), transaction.atomic():
        queue.delete()

    ticket.refresh_from_db()
    assert ServiceLocation.objects.filter(pk=queue.pk).exists()
    assert ticket.queue_id == queue.pk
    assert _evidence_counts(ticket) == before


def test_service_location_admin_disables_hard_delete_but_allows_deactivation(
    client,
    basic_world,
) -> None:
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name="Deactivation-first queue",
    )
    ticket = _ticket(basic_world, queue=queue)
    before = _evidence_counts(ticket)
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="QUEUE-OTHER",
        name="Other queue office",
    )
    client.force_login(_admin_user())
    delete_url = reverse("admin:organisations_servicelocation_delete", args=[queue.pk])

    assert client.get(delete_url, secure=True).status_code == 403
    assert client.post(delete_url, {"post": "yes"}, secure=True).status_code == 403

    change = client.post(
        reverse("admin:organisations_servicelocation_change", args=[queue.pk]),
        {
            "office": str(other_office.id),
            "name": "Renamed without custody",
            "is_active": "",
            "_save": "Save",
        },
        secure=True,
    )

    assert change.status_code == 302
    queue.refresh_from_db()
    ticket.refresh_from_db()
    assert queue.is_active is False
    assert queue.office_id == basic_world["office"].id
    assert queue.name == "Deactivation-first queue"
    assert ticket.queue_id == queue.pk
    assert _evidence_counts(ticket) == before


def test_0010_changes_queue_deletion_from_set_null_to_protect_and_rolls_back() -> None:
    from django.db.migrations.executor import MigrationExecutor

    previous = "0009_protect_ticket_assignee"
    leaf = "0010_protect_ticket_queue"
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", previous)])
        before_apps = executor.loader.project_state([("tickets", previous)]).apps
        before_field = before_apps.get_model("tickets", "Ticket")._meta.get_field("queue")
        assert before_field.remote_field.on_delete is SET_NULL

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", leaf)])
        after_apps = executor.loader.project_state([("tickets", leaf)]).apps
        after_field = after_apps.get_model("tickets", "Ticket")._meta.get_field("queue")
        assert after_field.remote_field.on_delete is PROTECT

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", previous)])
        rollback_apps = executor.loader.project_state([("tickets", previous)]).apps
        rollback_field = rollback_apps.get_model("tickets", "Ticket")._meta.get_field("queue")
        assert rollback_field.remote_field.on_delete is SET_NULL
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes("tickets"))
