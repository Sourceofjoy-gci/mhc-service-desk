"""Unit tests for the tickets domain services.

Exercises ticket numbering, creation, and the workflow transition rules
(FR-038, FR-040, FR-041, FR-022).
"""
from __future__ import annotations

import pytest

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.identity_access.models import User
from apps.organisations.models import Office, Region
from apps.tickets import services
from apps.workflow.models import Status, Transition
from apps.workflow.shortcuts import seed_workflow_for_tests

pytestmark = pytest.mark.django_db


def _actor(*groups: str) -> User:
    user = User.objects.create(
        username=f"actor-{User.objects.count()}",
        keycloak_subject=f"actor-subject-{User.objects.count()}",
        keycloak_groups=list(groups),
    )
    user._groups = list(groups)
    return user


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
    event = ticket.custody_events.get()
    assert event.sequence == 1
    assert event.event_type == "created"
    assert event.previous_status is None
    assert event.new_status == {"code": "new", "label": "New"}
    assert event.previous_queue is None
    assert event.new_queue is None
    assert event.actor_kind == "system"
    assert event.source_process == "ticket.create"


def assert_latest_transition_custody(updated, actor, expected_type):
    event = updated.custody_events.order_by("sequence").last()
    assert event is not None
    assert event.event_type == expected_type
    assert event.previous_status["code"] != event.new_status["code"]
    assert event.actor_subject == actor.keycloak_subject
    assert event.actor_kind == "user"
    assert event.previous_queue is None
    assert event.new_queue is None


def test_valid_transition_succeeds(basic_world):
    actor = _actor("ops-agents")
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
    ticket = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="triage",
    )
    assert ticket.status.code == "triage"
    assert ticket.custody_events.count() == 2
    assert_latest_transition_custody(ticket, actor, "status_changed")


def test_invalid_transition_raises(basic_world):
    actor = _actor("ops-agents")
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
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="closed",
        )


def test_resolution_required_for_resolved_transition(basic_world):
    actor = _actor("ops-agents")
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
    ticket = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="triage",
    )
    ticket = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="in_progress",
    )
    # Resolved requires resolution_code and summary
    with pytest.raises(services.TransitionError):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="resolved",
        )
    ticket = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="resolved",
        resolution_code="INFO_PROVIDED", resolution_summary="Called the requester with the answer.",
    )
    assert ticket.status.code == "resolved"
    assert ticket.resolution_code == "INFO_PROVIDED"
    assert ticket.resolved_at is not None


def test_stale_transition_changes_nothing_and_records_nothing(basic_world):
    from datetime import timedelta

    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent

    actor = _actor("ops-agents")
    ticket = services.create_ticket(
        domain="operational",
        title="Concurrent transition",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    stale = ticket.updated_at - timedelta(microseconds=1)
    history_count = ticket.transition_history.count()
    event_count = AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.transitioned"
    ).count()

    with pytest.raises(services.TicketConflictError):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=stale,
            to_status_code="triage",
        )

    ticket.refresh_from_db()
    assert ticket.status.code == "new"
    assert ticket.transition_history.count() == history_count
    assert AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.transitioned"
    ).count() == event_count
    assert not OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type="ticket.transitioned"
    ).exists()


def test_role_restricted_transition_is_forbidden_without_mutation(basic_world):
    from apps.tickets.models import OutboxEvent

    actor = _actor("ops-agents")
    ticket = services.create_ticket(
        domain="operational",
        title="Restricted transition",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-supervisors"
    transition.save(update_fields=["required_role"])
    previous_updated_at = ticket.updated_at

    with pytest.raises(services.TicketPermissionError):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="triage",
        )

    ticket.refresh_from_db()
    assert ticket.status.code == "new"
    assert ticket.updated_at == previous_updated_at
    assert not OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type="ticket.transitioned"
    ).exists()


def test_resolve_reopen_and_close_record_lifecycle_and_canonical_events(basic_world):
    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent
    from apps.workflow.models import Status

    actor = _actor("ops-agents")
    ticket = services.create_ticket(
        domain="operational",
        title="Lifecycle transition",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )

    for target in ("triage", "in_progress"):
        ticket = services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code=target,
        )

    with pytest.raises(services.TransitionError):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="resolved",
        )

    before_history = ticket.transition_history.count()
    before_audits = AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.transitioned"
    ).count()
    before_outbox = OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type="ticket.transitioned"
    ).count()
    ticket = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="resolved",
        resolution_code="INFO_PROVIDED",
        resolution_summary="Requester received an answer.",
    )
    assert ticket.resolution_code == "INFO_PROVIDED"
    assert ticket.resolution_summary == "Requester received an answer."
    assert ticket.resolved_at is not None
    assert ticket.closed_at is None
    assert ticket.transition_history.count() == before_history + 1
    assert AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.transitioned"
    ).count() == before_audits + 1
    assert OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type="ticket.transitioned"
    ).count() == before_outbox + 1

    reopened = Status.objects.create(
        domain="operational", code="reopened", name="Reopened", order=95
    )
    Transition.objects.create(
        domain="operational",
        from_status=ticket.status,
        to_status=reopened,
        name="Reopen",
    )
    old_resolution = {
        "resolution_code": ticket.resolution_code,
        "resolution_summary": ticket.resolution_summary,
        "resolved_at": str(ticket.resolved_at),
    }
    ticket = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="reopened",
        reason="Requester supplied new information",
    )
    assert ticket.reopened_at is not None
    assert ticket.resolution_code == ""
    assert ticket.resolution_summary == ""
    assert ticket.resolved_at is None
    reopen_event = AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.transitioned"
    ).latest("occurred_at")
    assert reopen_event.payload["before"] | old_resolution == reopen_event.payload["before"]
    assert reopen_event.payload["after"]["resolution_code"] == ""
    assert reopen_event.payload["after"]["resolution_summary"] == ""
    assert reopen_event.payload["after"]["resolved_at"] is None
    assert reopen_event.payload["metadata"] == {
        "reason": "Requester supplied new information"
    }
    assert_latest_transition_custody(ticket, actor, "reopened")

    Transition.objects.create(
        domain="operational",
        from_status=reopened,
        to_status=Status.objects.get(domain="operational", code="closed"),
        name="Close",
    )
    ticket = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="closed",
    )
    assert ticket.closed_at is not None
    assert_latest_transition_custody(ticket, actor, "closed")


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
