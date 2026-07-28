"""Tests for the IT child-ticket sanitised pattern (PRD §11.4)."""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.catalogue.models import RequestType
from apps.sla.models import SlaPauseHistory, SlaPolicy
from apps.sla.services import instantiate_slas
from apps.tickets import it_child, services
from apps.tickets.models import OutboxEvent, TicketLink
from apps.workflow.models import Status, TransitionHistory

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


def test_it_child_creation_records_the_actual_existing_parent_waiting_reason(world):
    from apps.audit.models import AuditEvent
    from apps.workflow.models import Status

    parent = services.create_ticket(
        domain="operational", title="X", description="",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email", actor_subject="creator",
    )
    parent.status = Status.objects.get(domain="operational", code="waiting_it")
    parent.waiting_reason = "Waiting on vendor escalation"
    parent.save(update_fields=["status", "waiting_reason", "updated_at"])

    it_child.create_it_child_ticket(
        parent=parent, summary="Investigate", requester=world["contact"],
        requester_office=world["office"], technical_priority="P3", actor_subject="tester",
    )

    event = AuditEvent.objects.filter(
        object_id=str(parent.id), action="ticket.transitioned",
    ).latest("occurred_at")
    assert event.payload["before"] == {
        "waiting_reason": "Waiting on vendor escalation",
    }
    assert event.payload["after"] == {"waiting_reason": "Waiting for IT"}


def test_child_sync_records_the_actual_non_default_parent_waiting_reason(world):
    from apps.audit.models import AuditEvent
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
    parent.waiting_reason = "Awaiting privileged-access approval"
    parent.save(update_fields=["waiting_reason", "updated_at"])
    child.status = Status.objects.get(domain="it", code="resolved")
    child.save(update_fields=["status", "updated_at"])

    it_child.sync_child_status_to_parent(child=child, actor_subject="sync-agent")

    event = AuditEvent.objects.filter(
        object_id=str(parent.id), action="ticket.transitioned",
    ).latest("occurred_at")
    assert event.payload["before"] == {
        "status": "waiting_it",
        "waiting_reason": "Awaiting privileged-access approval",
    }
    assert event.payload["after"] == {"status": "in_progress", "waiting_reason": ""}


def test_it_child_parent_transition_pauses_and_resumes_sla_without_extra_events(world):
    parent = services.create_ticket(
        domain="operational",
        title="IT dependency",
        description="",
        requester=world["contact"],
        service=world["gen_info"],
        request_type=world["op_rt"],
        office=world["office"],
        channel="email",
        actor_subject="creator",
    )
    parent.status = Status.objects.get(domain="operational", code="in_progress")
    parent.save(update_fields=["status", "updated_at"])
    instantiate_slas(
        ticket=parent,
        policy=SlaPolicy.objects.get(domain="operational", priority=parent.priority),
    )
    resolution_sla = parent.sla_instances.get(kind="resolution")
    before_history = TransitionHistory.objects.filter(ticket=parent).count()
    before_audits = AuditEvent.objects.filter(
        object_id=str(parent.id),
        action="ticket.transitioned",
    ).count()
    before_outbox = OutboxEvent.objects.filter(
        aggregate_id=str(parent.id),
        event_type="ticket.transitioned",
    ).count()

    child = it_child.create_it_child_ticket(
        parent=parent,
        summary="Investigate dependency",
        requester=world["contact"],
        requester_office=world["office"],
        technical_priority="P3",
        actor_subject="ops-agent",
    )

    resolution_sla.refresh_from_db()
    assert resolution_sla.state == "paused_it"
    pause = SlaPauseHistory.objects.get(instance=resolution_sla)
    assert pause.state == "paused_it"
    assert pause.actor_subject == "ops-agent"
    assert TransitionHistory.objects.filter(ticket=parent).count() == before_history + 1
    assert AuditEvent.objects.filter(
        object_id=str(parent.id), action="ticket.transitioned"
    ).count() == before_audits + 1
    assert OutboxEvent.objects.filter(
        aggregate_id=str(parent.id), event_type="ticket.transitioned"
    ).count() == before_outbox + 1

    child.status = Status.objects.get(domain="it", code="resolved")
    child.save(update_fields=["status", "updated_at"])
    it_child.sync_child_status_to_parent(
        child=child,
        actor_subject="it-sync-agent",
    )

    parent.refresh_from_db()
    resolution_sla.refresh_from_db()
    sla_history = list(
        SlaPauseHistory.objects.filter(instance=resolution_sla).order_by("at", "id")
    )
    assert parent.status.code == "in_progress"
    assert resolution_sla.state == "active"
    assert [(item.state, item.actor_subject) for item in sla_history] == [
        ("paused_it", "ops-agent"),
        ("active", "it-sync-agent"),
    ]
    assert TransitionHistory.objects.filter(ticket=parent).count() == before_history + 2
    assert AuditEvent.objects.filter(
        object_id=str(parent.id), action="ticket.transitioned"
    ).count() == before_audits + 2
    assert OutboxEvent.objects.filter(
        aggregate_id=str(parent.id), event_type="ticket.transitioned"
    ).count() == before_outbox + 2
