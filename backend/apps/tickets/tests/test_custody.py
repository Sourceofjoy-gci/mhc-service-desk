"""Tests for the immutable internal ticket-custody ledger."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from apps.catalogue.models import RequestType
from apps.identity_access.models import User
from apps.tickets import custody
from apps.tickets.custody import (
    CustodyActor,
    CustodyEventInput,
    CustodyQueue,
    CustodyStatus,
    record_custody_events,
    verify_custody_chain,
)
from apps.tickets.models import Ticket, TicketCustodyEvent
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket(basic_world):
    request_type = RequestType.objects.get(service=basic_world["gen_info"], code="HOURS")
    return Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 1:06d}",
        domain="operational",
        title="Custody test",
        description="",
        status=Status.objects.get(domain="operational", code="new"),
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=request_type,
        office=basic_world["office"],
        channel="web",
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


def test_timestamp_less_custody_inputs_share_one_default_timestamp_and_keep_explicit_values(
    ticket, monkeypatch
):
    """A multi-event mutation must use one coherent default custody instant."""
    default_at = datetime(2026, 7, 30, 10, 15, 30, 123456, tzinfo=UTC)
    unused_later_at = datetime(2026, 7, 30, 10, 15, 30, 123457, tzinfo=UTC)
    explicit_at = datetime(2026, 7, 30, 10, 16, tzinfo=UTC)
    clock_values = iter((default_at, unused_later_at))
    monkeypatch.setattr(custody.timezone, "now", lambda: next(clock_values))

    events = record_custody_events(
        ticket=ticket,
        actor=CustodyActor.user(subject="agent-1", display_name="Agent One"),
        events=(
            CustodyEventInput.created(
                source_process="ticket.create",
                source_record_type="test",
                source_record_id="source-1",
            ),
            CustodyEventInput(
                event_type="queue_changed",
                source_process="ticket.routing",
                source_record_type="test",
                source_record_id="source-2",
                occurred_at=explicit_at,
            ),
            CustodyEventInput(
                event_type="status_changed",
                source_process="ticket.transition",
                source_record_type="test",
                source_record_id="source-3",
            ),
        ),
    )

    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.source_record_id for event in events] == ["source-1", "source-2", "source-3"]
    assert [event.occurred_at for event in events] == [default_at, explicit_at, default_at]
    assert [event.previous_hash for event in events] == [
        "",
        events[0].event_hash,
        events[1].event_hash,
    ]
    assert verify_custody_chain(ticket) is True


def test_user_actor_uses_the_staff_subject_and_display_name():
    from apps.tickets.custody import user_actor

    staff = User(
        username="staff-username",
        keycloak_subject="staff-subject",
        display_name="Staff Display",
    )

    actor = user_actor(staff)

    assert actor.kind == "user"
    assert actor.subject == "staff-subject"
    assert actor.display_name == "Staff Display"


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
    assert verify_custody_chain(ticket) is True


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

    if connection.vendor == "postgresql":
        with pytest.raises(DatabaseError, match="immutable"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE ticket_custody_event SET previous_hash = %s WHERE id = %s",
                    ["tampered", event.id],
                )
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ticket_custody_event SET previous_hash = %s WHERE id = %s",
            ["tampered", event.id],
        )

    assert verify_custody_chain(ticket) is False


def test_verify_custody_chain_rejects_a_sequence_gap(ticket):
    """The verifier must require every sequence number from one onward."""
    _, event = _two_event_chain(ticket)

    if connection.vendor == "postgresql":
        with pytest.raises(DatabaseError, match="immutable"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE ticket_custody_event SET sequence = %s WHERE id = %s",
                    [3, event.id],
                )
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ticket_custody_event SET sequence = %s WHERE id = %s",
            [3, event.id],
        )

    assert verify_custody_chain(ticket) is False


def test_verify_custody_chain_rejects_a_tampered_content_hash(ticket):
    """An event hash that no longer represents its content must be rejected."""
    _, event = _two_event_chain(ticket)

    if connection.vendor == "postgresql":
        with pytest.raises(DatabaseError, match="immutable"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE ticket_custody_event SET event_hash = %s WHERE id = %s",
                    ["0" * 64, event.id],
                )
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ticket_custody_event SET event_hash = %s WHERE id = %s",
            ["0" * 64, event.id],
        )

    assert verify_custody_chain(ticket) is False


@pytest.mark.django_db(transaction=True)
def test_postgresql_rejects_raw_custody_updates_and_deletes_but_allows_insert(ticket):
    """The database trigger must protect rows even when ORM guards are bypassed."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL trigger coverage")

    event = record_custody_events(
        ticket=ticket,
        actor=CustodyActor.system("trigger-test", "Trigger test"),
        events=(CustodyEventInput.created(source_process="test.trigger"),),
    )[0]

    with pytest.raises(DatabaseError, match="immutable"):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ticket_custody_event SET reason = 'tampered' WHERE id = %s",
                [event.id],
            )
    with pytest.raises(DatabaseError, match="immutable"):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ticket_custody_event WHERE id = %s", [event.id])

    def delete_with_old_guc() -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL mhc.allow_ticket_custody_delete = 'on'")
            cursor.execute("DELETE FROM ticket_custody_event WHERE id = %s", [event.id])

    with pytest.raises(DatabaseError, match="immutable"):
        delete_with_old_guc()
