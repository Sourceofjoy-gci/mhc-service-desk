"""Unit tests for the tickets domain services.

Exercises ticket numbering, creation, and the workflow transition rules
(FR-038, FR-040, FR-041, FR-022).
"""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office, Region
from apps.tickets import services
from apps.tickets.models import Ticket
from apps.workflow.models import Status, Transition
from apps.workflow.shortcuts import seed_workflow_for_tests

pytestmark = pytest.mark.django_db


@pytest.fixture
def basic_world(db):
    seed_workflow_for_tests()
    region = Region.objects.create(code="TST", name="Test")
    office = Office.objects.create(region=region, code="TST-1", name="Test Office")
    service = Service.objects.create(code="TST-SVC", name="Test service", domain="operational")
    rt = RequestType.objects.create(
        service=service,
        code="TST-RT",
        name="Test RT",
        default_priority="P3",
    )
    contact = Contact.objects.create(full_name="Tester", email="t@example.com")
    return {"office": office, "service": service, "request_type": rt, "contact": contact}


def test_ticket_numbering_is_per_domain_and_sequential(basic_world):
    a = services.create_ticket(
        domain="operational",
        title="First",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    b = services.create_ticket(
        domain="operational",
        title="Second",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    assert a.number.startswith("OP-")
    assert b.number.startswith("OP-")
    assert a.number != b.number


def test_create_ticket_records_initial_status_history(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    assert ticket.acknowledged_at is not None
    assert ticket.transition_history.count() == 1
    assert ticket.transition_history.first().from_status is None
    assert ticket.transition_history.first().to_status.code == "new"


def test_valid_transition_succeeds(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    services.transition_ticket(
        ticket=ticket, to_status_code="triage", actor_subject="tester"
    )
    assert ticket.status.code == "triage"


def test_invalid_transition_raises(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    # new -> closed is not in the workflow
    with pytest.raises(services.TransitionError):
        services.transition_ticket(
            ticket=ticket, to_status_code="closed", actor_subject="tester"
        )


def test_resolution_required_for_resolved_transition(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    services.transition_ticket(ticket=ticket, to_status_code="triage", actor_subject="t")
    services.transition_ticket(ticket=ticket, to_status_code="in_progress", actor_subject="t")
    # Resolved requires resolution_code and summary
    with pytest.raises(services.TransitionError):
        services.transition_ticket(
            ticket=ticket, to_status_code="resolved", actor_subject="t"
        )
    services.transition_ticket(
        ticket=ticket, to_status_code="resolved", actor_subject="t",
        resolution_code="INFO_PROVIDED", resolution_summary="Called the requester with the answer.",
    )
    assert ticket.status.code == "resolved"
    assert ticket.resolution_code == "INFO_PROVIDED"
    assert ticket.resolved_at is not None


def test_issue_requester_token_returns_raw_once(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    record, raw = services.issue_requester_token(ticket=ticket)
    assert raw
    assert len(raw) > 20
    assert record.token_hash != raw  # we never store the raw token


def test_create_ticket_records_one_matching_canonical_event_pair(basic_world):
    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent

    ticket = services.create_ticket(
        domain="operational",
        title="Canonical creation",
        description="private requester body",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
        actor_subject="creator-1",
    )

    audit = AuditEvent.objects.get(object_id=str(ticket.id), action="ticket.created")
    outbox = OutboxEvent.objects.get(aggregate_id=str(ticket.id), event_type="ticket.created")
    assert audit.payload == outbox.payload
    assert audit.payload["actor"] == "creator-1"
    assert audit.payload["before"] == {}
    assert audit.payload["after"]["domain"] == "operational"
    assert "private requester body" not in str(audit.payload)


def test_add_message_records_ids_and_character_count_without_body(basic_world):
    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent

    ticket = services.create_ticket(
        domain="operational",
        title="Message event",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
        actor_subject="creator",
    )
    body = "Sensitive message text"

    message = services.add_message(
        ticket=ticket,
        direction="outbound",
        body_text=body,
        actor_subject="agent-1",
        author_subject="agent-1",
    )

    audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.message.created",
    )
    outbox = OutboxEvent.objects.get(
        aggregate_id=str(ticket.id),
        event_type="ticket.message.created",
    )
    expected_after = {
        "message_id": str(message.id),
        "direction": "outbound",
        "character_count": len(body),
    }
    assert audit.payload == outbox.payload
    assert audit.payload["after"] == expected_after
    assert body not in str(audit.payload)


def test_add_internal_note_records_id_type_and_character_count_without_body(basic_world):
    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent

    ticket = services.create_ticket(
        domain="operational",
        title="Note event",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
        actor_subject="creator",
    )
    body = "Sensitive internal note"

    note = services.add_internal_note(
        ticket=ticket,
        body=body,
        author_subject="agent-1",
    )

    audit = AuditEvent.objects.get(object_id=str(ticket.id), action="ticket.note.created")
    outbox = OutboxEvent.objects.get(
        aggregate_id=str(ticket.id),
        event_type="ticket.note.created",
    )
    assert audit.payload == outbox.payload
    assert audit.payload["after"] == {
        "note_id": str(note.id),
        "type": "internal",
        "character_count": len(body),
    }
    assert body not in str(audit.payload)


def test_link_tickets_records_one_relationship_event_pair(basic_world):
    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent

    source = services.create_ticket(
        domain="operational",
        title="Source",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
        actor_subject="creator",
    )
    target = services.create_ticket(
        domain="operational",
        title="Target",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
        actor_subject="creator",
    )

    link = services.link_tickets(
        source=source,
        target=target,
        kind="related",
        actor_subject="agent-1",
    )

    audit = AuditEvent.objects.get(
        object_id=str(source.id),
        action="ticket.relationship.created",
    )
    outbox = OutboxEvent.objects.get(
        aggregate_id=str(source.id),
        event_type="ticket.relationship.created",
    )
    assert audit.payload == outbox.payload
    assert audit.payload["after"] == {
        "relationship_id": str(link.id),
        "kind": "related",
        "target_ticket_number": target.number,
    }


def test_problem_incident_relationship_uses_canonical_link_event(basic_world):
    from apps.audit.models import AuditEvent
    from apps.tickets.problem_change import ProblemManager
    from apps.workflow.models import Status

    Status.objects.create(
        domain="it",
        code="new",
        name="New",
        is_initial=True,
    )
    it_service = Service.objects.create(
        code="IT-INC",
        name="IT incidents",
        domain="it",
    )
    RequestType.objects.create(
        service=it_service,
        code="OUTAGE",
        name="Outage",
        default_priority="P2",
    )

    incident = services.create_ticket(
        domain="operational",
        title="Related incident",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
        actor_subject="creator",
    )

    problem = ProblemManager.open_problem(
        title="Repeated outage",
        description="Investigate recurrence",
        opened_by="problem-manager",
        related_incident_ids=[str(incident.id)],
    )

    event = AuditEvent.objects.get(
        object_id=str(incident.id),
        action="ticket.relationship.created",
    )
    assert event.payload["actor"] == "problem-manager"
    assert event.payload["after"]["target_ticket_number"] == problem.number
