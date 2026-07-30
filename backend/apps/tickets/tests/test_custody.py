"""Tests for the immutable internal ticket-custody ledger."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.utils import timezone

from apps.catalogue.models import RequestType
from apps.tickets import services
from apps.tickets.custody import (
    CustodyActor,
    CustodyEventInput,
    CustodyQueue,
    CustodyStatus,
    record_custody_events,
    verify_custody_chain,
)
from apps.tickets.models import TicketCustodyEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket(basic_world):
    request_type = RequestType.objects.get(service=basic_world["gen_info"], code="HOURS")
    return services.create_ticket(
        domain="operational",
        title="Custody test",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=request_type,
        office=basic_world["office"],
        channel="web",
        actor_subject="creator-1",
    )


def test_custody_event_is_ordered_by_ticket_sequence(ticket):
    TicketCustodyEvent.objects.create(
        ticket=ticket,
        sequence=2,
        event_type="assigned",
        actor_kind="user",
        actor_subject="supervisor-1",
        actor_display_name="Supervisor One",
        source_process="ticket.assignment",
        previous_hash="a" * 64,
        event_hash="b" * 64,
    )
    TicketCustodyEvent.objects.create(
        ticket=ticket,
        sequence=1,
        event_type="created",
        actor_kind="system",
        actor_subject="intake:web",
        actor_display_name="Web intake",
        source_process="ticket.create",
        previous_hash="",
        event_hash="a" * 64,
    )

    assert list(
        TicketCustodyEvent.objects.filter(ticket=ticket).values_list("sequence", flat=True)
    ) == [1, 2]


def test_existing_custody_event_cannot_be_saved_or_deleted(ticket):
    event = TicketCustodyEvent.objects.create(
        ticket=ticket,
        sequence=1,
        event_type="created",
        actor_kind="system",
        actor_subject="intake:web",
        actor_display_name="Web intake",
        source_process="ticket.create",
        previous_hash="",
        event_hash="a" * 64,
    )

    event.reason = "rewritten"
    with pytest.raises(ValidationError, match="immutable"):
        event.save()
    with pytest.raises(ValidationError, match="immutable"):
        event.delete()
    with pytest.raises(ValidationError, match="immutable"):
        TicketCustodyEvent.objects.filter(pk=event.pk).update(reason="rewritten")
    with pytest.raises(ValidationError, match="immutable"):
        TicketCustodyEvent.objects.filter(pk=event.pk).delete()
    with pytest.raises(ValidationError, match="immutable"):
        TicketCustodyEvent._base_manager.filter(pk=event.pk).update(reason="rewritten")
    with pytest.raises(ValidationError, match="immutable"):
        TicketCustodyEvent._base_manager.filter(pk=event.pk).delete()


def test_ticket_custody_sequence_is_unique(ticket):
    TicketCustodyEvent.objects.create(
        ticket=ticket,
        sequence=1,
        event_type="created",
        actor_kind="system",
        actor_subject="intake:web",
        actor_display_name="Web intake",
        source_process="ticket.create",
        previous_hash="",
        event_hash="a" * 64,
    )

    with pytest.raises(IntegrityError):
        TicketCustodyEvent.objects.create(
            ticket=ticket,
            sequence=1,
            event_type="assigned",
            actor_kind="user",
            actor_subject="supervisor-1",
            actor_display_name="Supervisor One",
            source_process="ticket.assignment",
            previous_hash="a" * 64,
            event_hash="b" * 64,
        )


def test_record_custody_events_builds_a_verifiable_hash_chain(ticket):
    """Changing a link in an otherwise valid chain must make verification fail."""
    actor = CustodyActor.user(subject="agent-1", display_name="Agent One")

    events = record_custody_events(
        ticket=ticket,
        actor=actor,
        events=(
            CustodyEventInput.created(
                source_process="ticket.create",
                new_status=CustodyStatus(code="new", label="New"),
            ),
            CustodyEventInput(
                event_type="queue_changed",
                source_process="ticket.routing",
                previous_queue=None,
                new_queue=CustodyQueue(id="queue-1", label="Estate intake"),
            ),
        ),
    )

    assert [event.sequence for event in events] == [1, 2]
    assert events[0].previous_hash == ""
    assert events[1].previous_hash == events[0].event_hash
    assert verify_custody_chain(ticket) is True


def test_record_custody_events_appends_to_the_existing_hash_chain(ticket):
    """Restarting sequence or hash state would break the append-only ledger."""
    actor = CustodyActor.user(subject="agent-1", display_name="Agent One")
    first_event = record_custody_events(
        ticket=ticket,
        actor=actor,
        events=(CustodyEventInput.created(source_process="ticket.create"),),
    )[0]

    next_event = record_custody_events(
        ticket=ticket,
        actor=actor,
        events=(
            CustodyEventInput(
                event_type="status_changed",
                source_process="ticket.transition",
                new_status=CustodyStatus(code="in_progress", label="In progress"),
            ),
        ),
    )[0]

    assert next_event.sequence == 2
    assert next_event.previous_hash == first_event.event_hash
    assert verify_custody_chain(ticket) is True


def test_naive_custody_timestamp_is_normalized_before_hashing_and_persistence(ticket):
    """A naive supplied timestamp must hash exactly as its reloaded DB value."""
    event = record_custody_events(
        ticket=ticket,
        actor=CustodyActor.user(subject="agent-1", display_name="Agent One"),
        events=(
            CustodyEventInput.created(
                source_process="ticket.create",
                occurred_at=datetime(2026, 7, 30, 10, 15, 30, 123456),
            ),
        ),
    )[0]

    event.refresh_from_db()

    assert timezone.is_aware(event.occurred_at)
    assert verify_custody_chain(ticket) is True


@pytest.mark.parametrize(
    ("occurred_at", "expected_utc"),
    [
        (
            datetime(2026, 7, 30, 10, 15, 30, 123456),
            datetime(2026, 7, 30, 10, 15, 30, 123456, tzinfo=UTC),
        ),
        (
            datetime(
                2026,
                7,
                30,
                12,
                15,
                30,
                123456,
                tzinfo=ZoneInfo("Africa/Mbabane"),
            ),
            datetime(2026, 7, 30, 10, 15, 30, 123456, tzinfo=UTC),
        ),
    ],
)
def test_custody_input_serialization_matches_reloaded_utc_timestamp(
    ticket,
    occurred_at: datetime,
    expected_utc: datetime,
):
    """Canonical input JSON must encode the instant persisted by the custody writer."""
    custody_input = CustodyEventInput.created(
        source_process="ticket.create",
        occurred_at=occurred_at,
    )

    event = record_custody_events(
        ticket=ticket,
        actor=CustodyActor.user(subject="agent-1", display_name="Agent One"),
        events=(custody_input,),
    )[0]
    event.refresh_from_db()

    expected_serialized = "2026-07-30T10:15:30.123456Z"
    assert custody_input.as_json()["occurred_at"] == expected_serialized
    assert event.occurred_at == expected_utc
    assert event.occurred_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == expected_serialized


def _two_event_chain(ticket) -> list[TicketCustodyEvent]:
    return record_custody_events(
        ticket=ticket,
        actor=CustodyActor.user(subject="agent-1", display_name="Agent One"),
        events=(
            CustodyEventInput.created(source_process="ticket.create"),
            CustodyEventInput(
                event_type="status_changed",
                source_process="ticket.transition",
            ),
        ),
    )


def test_verify_custody_chain_rejects_an_altered_previous_hash(ticket):
    """A changed link must not be accepted even when event content is otherwise valid."""
    _, event = _two_event_chain(ticket)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ticket_custody_event SET previous_hash = %s WHERE id = %s",
            ["tampered", event.id],
        )

    assert verify_custody_chain(ticket) is False


def test_verify_custody_chain_rejects_a_sequence_gap(ticket):
    """The verifier must require every sequence number from one onward."""
    _, event = _two_event_chain(ticket)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ticket_custody_event SET sequence = %s WHERE id = %s",
            [3, event.id],
        )

    assert verify_custody_chain(ticket) is False


def test_verify_custody_chain_rejects_a_tampered_content_hash(ticket):
    """An event hash that no longer represents its content must be rejected."""
    _, event = _two_event_chain(ticket)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ticket_custody_event SET event_hash = %s WHERE id = %s",
            ["0" * 64, event.id],
        )

    assert verify_custody_chain(ticket) is False
