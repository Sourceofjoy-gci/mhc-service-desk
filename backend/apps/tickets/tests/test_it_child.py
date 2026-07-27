"""Tests for the IT child-ticket sanitised pattern (PRD §11.4)."""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.catalogue.models import RequestType
from apps.tickets import it_child, services
from apps.tickets.models import TicketLink

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(basic_world, db):
    """basic_world already seeds workflow and SLA. Add custom request types."""
    op_rt = RequestType.objects.create(
        service=basic_world["gen_info"],
        code="X",
        name="X",
        default_priority="P3",
    )
    it_rt = RequestType.objects.create(
        service=basic_world["it_inc"],
        code="Y",
        name="Y",
        default_priority="P3",
    )
    return {**basic_world, "op_rt": op_rt, "it_rt": it_rt}


def test_create_it_child_records_link_and_parent_status(world):
    parent = services.create_ticket(
        domain="operational", title="Email issue", description="",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email",
    )
    child = it_child.create_it_child_ticket(
        parent=parent, summary="Investigate email routing", requester=world["contact"],
        requester_office=world["office"], technical_priority="P2", actor_subject="tester",
    )
    assert child.domain == "it"
    assert child.number.startswith("IT-")
    assert TicketLink.objects.filter(from_ticket=child, to_ticket=parent, kind="it_child").exists()
    parent.refresh_from_db()
    assert parent.status.code == "waiting_it"
    assert parent.waiting_reason == "Waiting for IT"


def test_child_copies_only_approved_fields(world):
    parent = services.create_ticket(
        domain="operational", title="X", description="PRIVATE: not for IT",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email", matter_reference="EST-9999",
    )
    child = it_child.create_it_child_ticket(
        parent=parent, summary="Investigate", requester=world["contact"],
        requester_office=world["office"], technical_priority="P3",
        carry_matter_reference=True, actor_subject="tester",
    )
    assert child.description == ""
    assert "PRIVATE" not in child.title
    assert child.matter_reference == "EST-9999"


def test_child_resolution_syncs_parent_to_in_progress(world):
    parent = services.create_ticket(
        domain="operational", title="X", description="",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email",
    )
    child = it_child.create_it_child_ticket(
        parent=parent, summary="Investigate", requester=world["contact"],
        requester_office=world["office"], technical_priority="P3", actor_subject="tester",
    )
    from apps.workflow.models import Status
    target = Status.objects.get(domain="it", code="resolved")
    child.status = target
    child.resolution_code = "DONE"
    child.resolution_summary = "Fixed"
    child.resolved_at = timezone.now()
    child.save()
    it_child.sync_child_status_to_parent(child=child, actor_subject="tester")
    parent.refresh_from_db()
    assert parent.status.code == "in_progress"
    assert parent.waiting_reason == ""


def test_it_child_material_mutations_have_canonical_event_pairs(world):
    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent

    parent = services.create_ticket(
        domain="operational", title="X", description="private parent body",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email", actor_subject="creator",
    )
    child = it_child.create_it_child_ticket(
        parent=parent, summary="Sanitised investigation", requester=world["contact"],
        requester_office=world["office"], technical_priority="P3", actor_subject="tester",
    )

    child_events = AuditEvent.objects.filter(object_id=str(child.id))
    parent_events = AuditEvent.objects.filter(object_id=str(parent.id))
    assert child_events.filter(action="ticket.created").count() == 1
    assert child_events.filter(action="ticket.relationship.created").count() == 1
    assert parent_events.filter(action="ticket.transitioned").count() == 1
    for audit in (*child_events, *parent_events):
        assert OutboxEvent.objects.filter(
            aggregate_id=audit.object_id,
            event_type=audit.action,
            payload=audit.payload,
        ).count() == 1
        assert "private parent body" not in str(audit.payload)


def test_child_to_parent_sync_records_one_canonical_transition_pair(world):
    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent
    from apps.workflow.models import Status

    parent = services.create_ticket(
        domain="operational", title="X", description="",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email", actor_subject="creator",
    )
    child = it_child.create_it_child_ticket(
        parent=parent, summary="Investigate", requester=world["contact"],
        requester_office=world["office"], technical_priority="P3", actor_subject="tester",
    )
    child.status = Status.objects.get(domain="it", code="resolved")
    child.save(update_fields=["status", "updated_at"])
    before = AuditEvent.objects.filter(
        object_id=str(parent.id), action="ticket.transitioned",
    ).count()

    it_child.sync_child_status_to_parent(child=child, actor_subject="sync-agent")

    event = AuditEvent.objects.filter(
        object_id=str(parent.id), action="ticket.transitioned",
    ).latest("occurred_at")
    assert AuditEvent.objects.filter(
        object_id=str(parent.id), action="ticket.transitioned",
    ).count() == before + 1
    assert event.payload["actor"] == "sync-agent"
    assert event.payload["before"] == {
        "status": "waiting_it",
        "waiting_reason": "Waiting for IT",
    }
    assert event.payload["after"] == {"status": "in_progress", "waiting_reason": ""}
    assert OutboxEvent.objects.filter(
        aggregate_id=str(parent.id),
        event_type="ticket.transitioned",
        payload=event.payload,
    ).count() == 1
