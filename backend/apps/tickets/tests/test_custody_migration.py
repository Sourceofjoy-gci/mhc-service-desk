"""Migration-level reconstruction tests for the custody ledger."""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.models.deletion import CASCADE, DO_NOTHING

from apps.audit.models import AuditEvent
from apps.catalogue.models import RequestType
from apps.identity_access.models import User
from apps.organisations.models import ServiceLocation
from apps.tickets.activity import build_ticket_activity
from apps.tickets.custody import verify_custody_chain
from apps.tickets.models import Ticket
from apps.workflow.models import Status, TransitionHistory

pytestmark = pytest.mark.django_db(transaction=True)


def test_0005_table_rolls_back_and_restores_through_current_leaf():
    """The original custody-table migration must reverse and replay cleanly."""
    from django.db.migrations.executor import MigrationExecutor

    leaf = "0008_harden_ticket_custody_contract"
    table = "ticket_custody_event"
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", "0004_ticket_next_action_ticket_next_action_at")])

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", "0005_ticketcustodyevent")])
        forward_apps = executor.loader.project_state([("tickets", "0005_ticketcustodyevent")]).apps
        assert forward_apps.get_model("tickets", "TicketCustodyEvent") is not None
        assert table in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", "0004_ticket_next_action_ticket_next_action_at")])
        backward_apps = executor.loader.project_state(
            [("tickets", "0004_ticket_next_action_ticket_next_action_at")]
        ).apps
        with pytest.raises(LookupError):
            backward_apps.get_model("tickets", "TicketCustodyEvent")
        assert table not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", leaf)])
        restored_apps = executor.loader.project_state([("tickets", leaf)]).apps
        assert restored_apps.get_model("tickets", "TicketCustodyEvent") is not None
        assert table in connection.introspection.table_names()
    finally:
        MigrationExecutor(connection).migrate([("tickets", leaf)])


def _ticket(basic_world, *, number: str) -> Ticket:
    return Ticket.objects.create(
        number=number,
        domain="operational",
        title="Legacy custody history",
        status=Status.objects.get(domain="operational", code="new"),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
    )


def _user(*, username: str, subject: str) -> User:
    return User.objects.create_user(
        username=username,
        password="not-used",
        keycloak_subject=subject,
        display_name=f"{username.title()} Agent",
    )


def _audit(
    *,
    ticket: Ticket,
    action: str,
    actor_subject: str,
    before: dict[str, object],
    after: dict[str, object],
    occurred_at: datetime,
) -> AuditEvent:
    event = AuditEvent.objects.create(
        actor_subject=actor_subject,
        action=action,
        object_type="ticket",
        object_id=str(ticket.id),
        payload={"before": before, "after": after},
        payload_hash="0" * 64,
    )
    AuditEvent.objects.filter(pk=event.pk).update(occurred_at=occurred_at)
    event.refresh_from_db()
    return event


def test_backfill_reconstructs_deterministic_verifiable_history(basic_world):
    """Dropping a source or changing sort order would alter this ledger."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    ticket = _ticket(basic_world, number="OP-LEGACY-BACKFILL-1")
    first = _user(username="first", subject="agent-first")
    second = _user(username="second", subject="agent-second")
    first_queue = ServiceLocation.objects.create(office=basic_world["office"], name="Legacy intake")
    created_at = datetime(2025, 1, 2, 8, 0, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=created_at)
    _audit(
        ticket=ticket,
        action="ticket.created",
        actor_subject="intake-worker",
        before={},
        after={},
        occurred_at=created_at,
    )
    _audit(
        ticket=ticket,
        action="ticket.assignment.changed",
        actor_subject="supervisor",
        before={"assignee": None},
        after={"assignee": str(first.id)},
        occurred_at=created_at + timedelta(minutes=1),
    )
    _audit(
        ticket=ticket,
        action="ticket.work_state.changed",
        actor_subject="supervisor",
        before={"queue": None},
        after={"queue": str(first_queue.id)},
        occurred_at=created_at + timedelta(minutes=2),
    )
    _audit(
        ticket=ticket,
        action="ticket.assignment.changed",
        actor_subject="supervisor",
        before={"assignee": str(first.id)},
        after={"assignee": str(second.id)},
        occurred_at=created_at + timedelta(minutes=3),
    )
    closed = Status.objects.get(domain="operational", code="closed")
    transition = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=ticket.status,
        to_status=closed,
        actor_subject="agent-second",
        reason="Resolved legacy ticket",
    )
    TransitionHistory.objects.filter(pk=transition.pk).update(
        occurred_at=created_at + timedelta(minutes=4)
    )

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)
    backfill_ticket_custody(django_apps, None)

    assert list(ticket.custody_events.values_list("event_type", flat=True)) == [
        "created",
        "assigned",
        "queue_changed",
        "reassigned",
        "closed",
    ]
    assert ticket.custody_events.count() == 5
    created, assigned, queue_changed, reassigned, closed_event = ticket.custody_events.all()
    assert created.new_status == {"code": "new", "label": "New"}
    assert assigned.new_owner == {
        "id": str(first.id),
        "subject": "agent-first",
        "display_name": "First Agent",
    }
    assert queue_changed.new_queue == {"id": str(first_queue.id), "label": "Legacy intake"}
    assert reassigned.previous_owner["id"] == str(first.id)
    assert reassigned.new_owner["id"] == str(second.id)
    assert closed_event.new_status == {"code": "closed", "label": "Closed"}
    assert verify_custody_chain(ticket) is True


def test_backfill_and_activity_keep_later_transition_to_an_initial_status(basic_world):
    """Only the null-from creation transition may be represented by the created custody event."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    ticket = _ticket(basic_world, number="OP-LEGACY-CREATION-DEDUPE")
    created_at = datetime(2025, 1, 2, 8, 0, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=created_at)
    _audit(
        ticket=ticket,
        action="ticket.created",
        actor_subject="intake-worker",
        before={},
        after={},
        occurred_at=created_at,
    )
    initial = Status.objects.get(domain="operational", code="new")
    triage = Status.objects.get(domain="operational", code="triage")
    closed = Status.objects.get(domain="operational", code="closed")
    creation = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=None,
        to_status=initial,
        actor_subject="intake-worker",
    )
    second_null_from = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=None,
        to_status=triage,
        actor_subject="legacy-import",
        reason="Separate imported workflow fact",
    )
    later_to_initial = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=triage,
        to_status=initial,
        actor_subject="agent-one",
        reason="Returned to intake",
    )
    later_closed = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=initial,
        to_status=closed,
        actor_subject="agent-one",
        reason="Completed",
    )
    TransitionHistory.objects.filter(pk=creation.pk).update(occurred_at=created_at)
    TransitionHistory.objects.filter(pk=second_null_from.pk).update(
        occurred_at=created_at + timedelta(seconds=30)
    )
    TransitionHistory.objects.filter(pk=later_to_initial.pk).update(
        occurred_at=created_at + timedelta(minutes=1)
    )
    TransitionHistory.objects.filter(pk=later_closed.pk).update(
        occurred_at=created_at + timedelta(minutes=2)
    )
    Status.objects.filter(domain="operational", is_initial=True).update(is_initial=False)
    Status.objects.filter(pk=triage.pk).update(is_initial=True)

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)

    custody_events = list(ticket.custody_events.all())
    activity = build_ticket_activity(ticket)

    assert [event.event_type for event in custody_events] == [
        "created",
        "status_changed",
        "status_changed",
        "closed",
    ]
    assert custody_events[0].new_status == {"code": "new", "label": "New"}
    assert custody_events[0].source_record_type == "workflow_transition"
    assert custody_events[0].source_record_id == str(creation.id)
    assert [event.source_record_id for event in custody_events] == [
        str(ticket.custody_events.get(event_type="created").source_record_id),
        str(second_null_from.id),
        str(later_to_initial.id),
        str(later_closed.id),
    ]
    assert [
        (item["type"], item["payload"]["from"], item["payload"]["to"])
        for item in activity
        if item["type"] in {"custody_event", "status_transition"}
    ] == [
        ("custody_event", None, "new"),
        ("status_transition", None, "triage"),
        ("status_transition", "triage", "new"),
        ("status_transition", "new", "closed"),
    ]
    assert not [item for item in activity if item["id"] == f"transition:{creation.id}"]
    imported_fact = [
        item
        for item in activity
        if item["payload"].get("source_record_id") == str(second_null_from.id)
    ]
    assert len(imported_fact) == 1
    assert imported_fact[0]["payload"]["from"] is None
    assert imported_fact[0]["payload"]["to"] == "triage"
    assert verify_custody_chain(ticket) is True


@pytest.mark.django_db(transaction=True)
def test_0006_rollback_restores_trigger_fk_index_and_legacy_data(basic_world):
    """Rollback intentionally keeps backfill rows but must remove DB protection."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL migration coverage")
    from django.db.migrations.executor import MigrationExecutor

    ticket = _ticket(basic_world, number="OP-EXECUTOR-LEGACY")
    cascade_ticket = _ticket(basic_world, number="OP-EXECUTOR-CASCADE")
    occurred_at = datetime(2025, 2, 1, tzinfo=UTC)
    Ticket.objects.filter(pk__in=[ticket.pk, cascade_ticket.pk]).update(created_at=occurred_at)
    _audit(
        ticket=ticket,
        action="ticket.created",
        actor_subject="legacy-executor",
        before={},
        after={},
        occurred_at=occurred_at,
    )
    _audit(
        ticket=cascade_ticket,
        action="ticket.created",
        actor_subject="legacy-executor",
        before={},
        after={},
        occurred_at=occurred_at,
    )
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([("tickets", "0005_ticketcustodyevent")])
        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", "0006_backfill_ticket_custody")])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = %s)",
                ["ticket_custody_immutable"],
            )
            assert cursor.fetchone()[0] is True
            cursor.execute("SELECT to_regclass(%s)", ["auditevent_ticket_object_lookup_idx"])
            assert cursor.fetchone()[0] is not None
            cursor.execute(
                "SELECT count(*) FROM ticket_custody_event WHERE ticket_id = %s", [ticket.pk]
            )
            assert cursor.fetchone()[0] == 1
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ticket WHERE id = %s", [cascade_ticket.pk])
            cursor.execute(
                "SELECT count(*) FROM ticket_custody_event WHERE ticket_id = %s",
                [cascade_ticket.pk],
            )
            assert cursor.fetchone()[0] == 0
        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", "0005_ticketcustodyevent")])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = %s)",
                ["ticket_custody_immutable"],
            )
            assert cursor.fetchone()[0] is False
            cursor.execute("SELECT to_regclass(%s)", ["auditevent_ticket_object_lookup_idx"])
            assert cursor.fetchone()[0] is None
        with pytest.raises(DatabaseError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("DELETE FROM ticket WHERE id = %s", [ticket.pk])
    finally:
        MigrationExecutor(connection).migrate([("tickets", "0008_harden_ticket_custody_contract")])


def test_0007_keeps_database_cascade_while_collector_skips_custody():
    """The ORM state omits custody, but the database cascade remains authoritative."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL migration coverage")
    from django.db.migrations.executor import MigrationExecutor

    migration = "0007_ticket_custody_collector_state"
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", "0006_backfill_ticket_custody")])
        before_apps = (
            MigrationExecutor(connection)
            .loader.project_state([("tickets", "0006_backfill_ticket_custody")])
            .apps
        )
        assert (
            before_apps.get_model("tickets", "TicketCustodyEvent")
            ._meta.get_field("ticket")
            .remote_field.on_delete
            is CASCADE
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", migration)])
        after_apps = (
            MigrationExecutor(connection).loader.project_state([("tickets", migration)]).apps
        )
        assert (
            after_apps.get_model("tickets", "TicketCustodyEvent")
            ._meta.get_field("ticket")
            .remote_field.on_delete
            is DO_NOTHING
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conrelid = 'ticket_custody_event'::regclass "
                "AND confrelid = 'ticket'::regclass AND contype = 'f'"
            )
            assert cursor.fetchone() == ("c",)

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", "0006_backfill_ticket_custody")])
        rollback_apps = (
            MigrationExecutor(connection)
            .loader.project_state([("tickets", "0006_backfill_ticket_custody")])
            .apps
        )
        assert (
            rollback_apps.get_model("tickets", "TicketCustodyEvent")
            ._meta.get_field("ticket")
            .remote_field.on_delete
            is CASCADE
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conrelid = 'ticket_custody_event'::regclass "
                "AND confrelid = 'ticket'::regclass AND contype = 'f'"
            )
            assert cursor.fetchone() == ("c",)
    finally:
        MigrationExecutor(connection).migrate(
            [("tickets", "0008_harden_ticket_custody_contract")]
        )


def test_0007_0008_and_rollback_enforce_their_distinct_delete_contracts(basic_world):
    """Only 0008 may require the approved gate, and it must reject child deletes."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL migration coverage")
    from django.db.migrations.executor import MigrationExecutor

    def ticket_with_custody(number: str):
        from apps.tickets.models import TicketCustodyEvent

        ticket = _ticket(basic_world, number=number)
        TicketCustodyEvent.objects.create(
            ticket=ticket,
            sequence=1,
            event_type="created",
            actor_kind="system",
            actor_subject="migration-test",
            actor_display_name="Migration test",
            source_process="test.migration",
            event_hash="a" * 64,
        )
        return ticket

    def raw_parent_delete(ticket_id) -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM ticket WHERE id = %s", [ticket_id])

    def raw_child_delete_with_gate(event_id) -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL mhc.allow_ticket_custody_delete = 'on'")
            cursor.execute(
                "DELETE FROM ticket_custody_event WHERE id = %s",
                [event_id],
            )

    try:
        MigrationExecutor(connection).migrate([("tickets", "0005_ticketcustodyevent")])
        MigrationExecutor(connection).migrate(
            [("tickets", "0007_ticket_custody_collector_state")]
        )
        fresh_0007 = ticket_with_custody("OP-MIGRATION-0007-FRESH")
        raw_parent_delete(fresh_0007.pk)
        assert not Ticket._base_manager.filter(pk=fresh_0007.pk).exists()

        MigrationExecutor(connection).migrate(
            [("tickets", "0008_harden_ticket_custody_contract")]
        )
        upgraded_0008 = ticket_with_custody("OP-MIGRATION-0008-GUARDED")
        upgraded_event = upgraded_0008.custody_events.get()
        with pytest.raises(DatabaseError, match="immutable"):
            raw_parent_delete(upgraded_0008.pk)
        with pytest.raises(DatabaseError, match="immutable"):
            raw_child_delete_with_gate(upgraded_event.pk)
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL mhc.allow_ticket_custody_delete = 'on'")
            cursor.execute("DELETE FROM ticket WHERE id = %s", [upgraded_0008.pk])
        assert not Ticket._base_manager.filter(pk=upgraded_0008.pk).exists()

        MigrationExecutor(connection).migrate(
            [("tickets", "0007_ticket_custody_collector_state")]
        )
        rolled_back_0007 = ticket_with_custody("OP-MIGRATION-0007-ROLLBACK")
        raw_parent_delete(rolled_back_0007.pk)
        assert not Ticket._base_manager.filter(pk=rolled_back_0007.pk).exists()
    finally:
        MigrationExecutor(connection).migrate(
            [("tickets", "0008_harden_ticket_custody_contract")]
        )


def test_backfill_synthesizes_only_a_minimal_legacy_created_event(basic_world):
    """A missing creation audit must not fabricate ownership or routing facts."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    ticket = _ticket(basic_world, number="OP-LEGACY-BACKFILL-2")
    created_at = datetime(2025, 1, 3, 8, 0, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=created_at)

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)

    event = ticket.custody_events.get()
    assert event.event_type == "created"
    assert event.occurred_at == created_at
    assert (event.actor_kind, event.actor_subject) == ("system", "legacy-backfill")
    assert event.previous_owner is None
    assert event.new_owner is None
    assert event.previous_queue is None
    assert event.new_queue is None
    assert verify_custody_chain(ticket) is True


def test_backfill_keeps_raw_assignment_direction_and_uses_explicit_tie_order(basic_world):
    """Deleted users and equal timestamps must not alter historical event order."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    ticket = _ticket(basic_world, number="OP-LEGACY-BACKFILL-TIES")
    created_at = datetime(2025, 1, 4, 8, 0, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=created_at)
    Status.objects.filter(domain="operational", is_initial=True).update(is_initial=False)
    Status.objects.create(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        domain="operational",
        code="legacy-first",
        name="Legacy first",
        is_initial=True,
        order=0,
    )
    Status.objects.create(
        id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        domain="operational",
        code="legacy-second",
        name="Legacy second",
        is_initial=True,
        order=0,
    )
    _audit(
        ticket=ticket,
        action="ticket.assignment.changed",
        actor_subject="legacy",
        before={"assignee": None},
        after={"assignee": "missing-user"},
        occurred_at=created_at,
    )
    _audit(
        ticket=ticket,
        action="ticket.work_state.changed",
        actor_subject="legacy",
        before={"queue": "missing-queue"},
        after={"queue": None},
        occurred_at=created_at,
    )
    _audit(
        ticket=ticket,
        action="ticket.assignment.changed",
        actor_subject="legacy",
        before={"assignee": "missing-user"},
        after={"assignee": None},
        occurred_at=created_at,
    )
    _audit(
        ticket=ticket,
        action="ticket.created",
        actor_subject="legacy",
        before={},
        after={},
        occurred_at=created_at,
    )

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)

    events = list(ticket.custody_events.all())
    assert events[0].event_type == "created"
    assert {event.event_type for event in events[1:]} == {
        "assigned",
        "unassigned",
        "queue_changed",
    }
    assert events[0].new_status == {"code": "legacy-first", "label": "Legacy first"}
    assigned = next(event for event in events if event.event_type == "assigned")
    unassigned = next(event for event in events if event.event_type == "unassigned")
    assert assigned.new_owner == {
        "id": "missing-user",
        "subject": None,
        "display_name": None,
        "raw_value": "missing-user",
        "unresolved": True,
    }
    assert unassigned.previous_owner == assigned.new_owner
    queue_event = next(event for event in events if event.event_type == "queue_changed")
    assert queue_event.previous_queue == {
        "id": "missing-queue",
        "label": None,
        "raw_value": "missing-queue",
        "unresolved": True,
    }
    assert queue_event.new_queue is None
    assert {event.actor_kind for event in events} == {"legacy_unknown"}
    assert verify_custody_chain(ticket) is True


def test_backfilled_unresolved_facts_do_not_depend_on_the_linked_audit(basic_world):
    """Editing or deleting a linked audit must not change immutable custody facts."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    ticket = _ticket(basic_world, number="OP-LEGACY-IMMUTABLE-FACTS")
    occurred_at = datetime(2025, 1, 4, 9, 0, tzinfo=UTC)
    audit = _audit(
        ticket=ticket,
        action="ticket.work_state.changed",
        actor_subject="deleted-supervisor",
        before={"assignee": "deleted-owner", "queue": "deleted-queue"},
        after={"assignee": None, "queue": None},
        occurred_at=occurred_at,
    )

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)
    AuditEvent.objects.filter(pk=audit.pk).update(
        payload={
            "before": {"assignee": "rewritten-owner", "queue": "rewritten-queue"},
            "after": {"assignee": None, "queue": None},
        }
    )

    activity = build_ticket_activity(ticket)
    owner_event = next(
        item for item in activity if item["payload"].get("action") == "unassigned"
    )
    queue_event = next(
        item for item in activity if item["payload"].get("action") == "queue_changed"
    )
    assert owner_event["payload"]["previous_owner"]["id"] == "deleted-owner"
    assert queue_event["payload"]["previous_queue"]["id"] == "deleted-queue"
    assert owner_event["payload"]["actor_kind"] == "legacy_unknown"

    AuditEvent.objects.filter(pk=audit.pk).delete()
    after_delete = build_ticket_activity(ticket)
    assert next(
        item for item in after_delete if item["payload"].get("action") == "unassigned"
    )["payload"]["previous_owner"]["id"] == "deleted-owner"
    assert next(
        item for item in after_delete if item["payload"].get("action") == "queue_changed"
    )["payload"]["previous_queue"]["id"] == "deleted-queue"


def test_blank_actors_on_real_legacy_sources_are_not_claimed_as_system(basic_world):
    """A blank source actor is unknown evidence, not a named system process."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    User.objects.create_user(
        username="malformed-empty-subject",
        keycloak_subject="",
        display_name="Must not become the actor",
    )
    ticket = _ticket(basic_world, number="OP-LEGACY-BLANK-ACTOR")
    created_at = datetime(2025, 1, 4, 10, 0, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=created_at)
    _audit(
        ticket=ticket,
        action="ticket.created",
        actor_subject="",
        before={},
        after={},
        occurred_at=created_at,
    )
    closed = Status.objects.get(domain="operational", code="closed")
    transition = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=ticket.status,
        to_status=closed,
        actor_subject="",
        reason="Imported closure",
    )
    TransitionHistory.objects.filter(pk=transition.pk).update(
        occurred_at=created_at + timedelta(minutes=1)
    )

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)

    created, closed_event = ticket.custody_events.all()
    assert (created.actor_kind, created.actor_subject) == ("legacy_unknown", "")
    assert (closed_event.actor_kind, closed_event.actor_subject) == (
        "legacy_unknown",
        "",
    )
    assert created.actor_display_name == "Unknown legacy actor"
    assert closed_event.actor_display_name == "Unknown legacy actor"
    assert verify_custody_chain(ticket) is True


def test_backfill_resolves_uppercase_uuid_snapshots(basic_world):
    """Valid UUID spellings must resolve even when legacy JSON uses uppercase."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    ticket = _ticket(basic_world, number="OP-LEGACY-UPPERCASE-UUID")
    user = _user(username="upper", subject="upper-subject")
    queue = ServiceLocation.objects.create(office=basic_world["office"], name="Upper queue")
    at = datetime(2025, 1, 5, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=at)
    _audit(
        ticket=ticket,
        action="ticket.assignment.changed",
        actor_subject="legacy",
        before={"assignee": None, "queue": None},
        after={"assignee": str(user.pk).upper(), "queue": str(queue.pk).upper()},
        occurred_at=at,
    )

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)

    assigned = ticket.custody_events.get(event_type="assigned")
    queue_changed = ticket.custody_events.get(event_type="queue_changed")
    assert assigned.new_owner["id"] == str(user.pk)
    assert assigned.new_owner["display_name"] == "Upper Agent"
    assert queue_changed.new_queue == {"id": str(queue.pk), "label": "Upper queue"}
    assert verify_custody_chain(ticket) is True
