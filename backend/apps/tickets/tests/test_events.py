"""Tests for canonical transactional ticket events."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from apps.audit.models import AuditEvent
from apps.catalogue.models import RequestType
from apps.tickets import services
from apps.tickets.custody import CustodyActor, CustodyEventInput
from apps.tickets.events import record_ticket_event
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket(basic_world):
    request_type = RequestType.objects.get(service=basic_world["gen_info"], code="HOURS")
    return services.create_ticket(
        domain="operational",
        title="Event test",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=request_type,
        office=basic_world["office"],
        channel="web",
        actor_subject="creator-1",
    )


def test_record_ticket_event_writes_matching_audit_and_outbox(ticket):
    audit, outbox = record_ticket_event(
        ticket=ticket,
        actor_subject="agent-1",
        action="ticket.assignment.changed",
        before={"assignee": None},
        after={"assignee": "agent-1"},
        metadata={"source": "workspace"},
    )
    expected = {
        "ticket_number": ticket.number,
        "actor": "agent-1",
        "before": {"assignee": None},
        "after": {"assignee": "agent-1"},
        "metadata": {"source": "workspace"},
    }
    canonical = json.dumps(
        expected,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()

    assert audit.payload == expected
    assert audit.payload_hash == hashlib.sha256(canonical).hexdigest()
    assert outbox.event_type == "ticket.assignment.changed"
    assert outbox.payload == expected


def test_create_ticket_rolls_back_when_audit_event_cannot_be_recorded(basic_world):
    request_type = RequestType.objects.get(service=basic_world["gen_info"], code="HOURS")
    before_tickets = Ticket.objects.count()
    before_outbox = OutboxEvent.objects.count()

    with (
        patch.object(AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")),
        pytest.raises(RuntimeError, match="audit unavailable"),
    ):
        services.create_ticket(
            domain="operational",
            title="Must roll back",
            description="",
            requester=basic_world["contact"],
            service=basic_world["gen_info"],
            request_type=request_type,
            office=basic_world["office"],
            channel="web",
            actor_subject="creator-2",
        )

    assert Ticket.objects.count() == before_tickets
    assert OutboxEvent.objects.count() == before_outbox


def test_record_ticket_event_normalizes_values_and_omits_unchanged_fields(ticket):
    next_action_at = datetime(2026, 7, 27, 10, 30, tzinfo=UTC)

    audit, outbox = record_ticket_event(
        ticket=ticket,
        actor_subject="agent-1",
        action="ticket.work_state.changed",
        before={"priority": "P3", "next_action_at": None},
        after={"priority": "P3", "next_action_at": next_action_at},
    )

    assert audit.payload["before"] == {"next_action_at": None}
    assert audit.payload["after"] == {
        "next_action_at": "2026-07-27 10:30:00+00:00",
    }
    assert outbox.payload == audit.payload


def test_record_ticket_event_rolls_back_audit_outbox_and_custody_together(ticket):
    """A custody-write failure must leave none of the transaction's rows persisted."""
    audit_count = AuditEvent.objects.filter(object_id=str(ticket.id)).count()
    outbox_count = OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count()
    custody_count = TicketCustodyEvent.objects.filter(ticket=ticket).count()

    with patch(
        "apps.tickets.custody.TicketCustodyEvent.objects.create",
        side_effect=RuntimeError("custody unavailable"),
    ):
        with pytest.raises(RuntimeError, match="custody unavailable"):
            record_ticket_event(
                ticket=ticket,
                actor_subject="agent-1",
                action="ticket.created",
                before={},
                after={"status": "new"},
                custody_actor=CustodyActor.user("agent-1", "Agent One"),
                custody_events=(
                    CustodyEventInput.created(source_process="ticket.create"),
                ),
            )

    assert AuditEvent.objects.filter(object_id=str(ticket.id)).count() == audit_count
    assert OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count() == outbox_count
    assert TicketCustodyEvent.objects.filter(ticket=ticket).count() == custody_count
