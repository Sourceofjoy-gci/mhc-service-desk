"""Regression coverage for SLA entitlement and evaluator consistency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from threading import Event, Thread
from typing import TypedDict
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.catalogue.models import Service
from apps.contacts.models import Contact
from apps.identity_access.models import Role, UserRole
from apps.organisations.models import Office
from apps.sla.models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy
from apps.sla.seed_sla import seed_sla
from apps.sla.serializers import serialize_sla_clock
from apps.sla.services import (
    add_business_seconds,
    business_seconds_between,
    complete_sla,
    evaluate_open_slas,
    pause_sla,
    resume_sla,
)
from apps.tickets import services as ticket_services
from apps.tickets.custody import verify_custody_chain
from apps.tickets.models import Ticket
from apps.tickets.seed_workflow import seed_workflow
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


class BasicWorld(TypedDict):
    gen_info: Service
    contact: Contact
    office: Office


def _mbabane_calendar(*, holidays: list[str] | None = None) -> BusinessCalendar:
    return BusinessCalendar.objects.create(
        name=f"Mbabane correctness {BusinessCalendar.objects.count()}",
        timezone="Africa/Mbabane",
        weekday_hours={str(day): [{"start": "08:00", "end": "17:00"}] for day in range(1, 6)},
        holidays=holidays or [],
    )


def test_add_business_seconds_uses_calendar_local_timezone() -> None:
    calendar = _mbabane_calendar()
    start = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)  # 08:00 in Mbabane

    assert add_business_seconds(start, 3600, calendar) == datetime(2026, 7, 27, 7, 0, tzinfo=UTC)


def test_add_business_seconds_applies_holiday_to_calendar_local_date() -> None:
    calendar = _mbabane_calendar(holidays=["2026-07-28"])
    start = datetime(2026, 7, 27, 14, 30, tzinfo=UTC)  # 16:30 local

    assert add_business_seconds(start, 3600, calendar) == datetime(2026, 7, 29, 6, 30, tzinfo=UTC)


def test_business_seconds_between_uses_calendar_local_slots() -> None:
    calendar = _mbabane_calendar()
    start = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    end = datetime(2026, 7, 27, 7, 0, tzinfo=UTC)

    assert business_seconds_between(start, end, calendar) == 3600


def test_business_seconds_between_counts_both_sides_of_dst_fall_fold() -> None:
    calendar = BusinessCalendar.objects.create(
        name="New York fold correctness",
        timezone="America/New_York",
        weekday_hours={"7": [{"start": "01:00", "end": "02:00"}]},
        holidays=[],
    )
    local_timezone = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, 1, 30, tzinfo=local_timezone, fold=0)
    end = datetime(2026, 11, 1, 1, 30, tzinfo=local_timezone, fold=1)

    assert business_seconds_between(start, end, calendar) == 3600


def test_calendar_validation_rejects_overlapping_weekly_intervals() -> None:
    calendar = _mbabane_calendar()
    calendar.holidays = ["2099-01-01"]
    calendar.weekday_hours = {
        "1": [
            {"start": "08:00", "end": "10:00"},
            {"start": "09:00", "end": "11:00"},
        ]
    }

    with pytest.raises(ValidationError, match="overlap"):
        calendar.full_clean()


def test_calendar_math_merges_legacy_overlapping_intervals() -> None:
    calendar = _mbabane_calendar()
    calendar.weekday_hours = {
        "1": [
            {"start": "08:00", "end": "10:00"},
            {"start": "09:00", "end": "11:00"},
        ]
    }
    calendar.save(update_fields=["weekday_hours"])
    start = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)  # 08:00 local
    end = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)  # 11:00 local

    assert business_seconds_between(start, end, calendar) == 3 * 3600


def _ticket(basic_world: BasicWorld, *, ticket_id: UUID | None = None) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        id=ticket_id or uuid4(),
        number=f"OP-202607-{Ticket.objects.count() + 993001:06d}",
        domain="operational",
        title="SLA correctness",
        status=Status.objects.get(domain="operational", code="in_progress"),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _instance(
    basic_world: BasicWorld,
    *,
    due_at: datetime,
    state: str = SlaInstance.State.ACTIVE,
    ticket_id: UUID | None = None,
) -> SlaInstance:
    ticket = _ticket(basic_world, ticket_id=ticket_id)
    policy = SlaPolicy.objects.get(domain="operational", priority="P3")
    return SlaInstance.objects.create(
        ticket=ticket,
        policy=policy,
        kind="resolution",
        state=state,
        started_at=due_at - timedelta(hours=2),
        due_at=due_at,
    )


def test_resume_restores_entitlement_after_pause_outlasts_original_deadline(
    basic_world: BasicWorld,
) -> None:
    paused_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    resumed_at = datetime(2026, 7, 27, 13, 0, tzinfo=UTC)
    instance = _instance(basic_world, due_at=paused_at + timedelta(hours=1))

    with freeze_time(paused_at):
        pause_sla(instance=instance, reason=SlaInstance.State.PAUSED_REQUESTER)
    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="requester_replied")

    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.ACTIVE
    assert instance.due_at == resumed_at + timedelta(hours=1)


def test_paused_clock_displays_frozen_entitlement_after_original_deadline(
    basic_world: BasicWorld,
) -> None:
    paused_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    later = datetime(2026, 7, 27, 13, 0, tzinfo=UTC)
    instance = _instance(basic_world, due_at=paused_at + timedelta(hours=1))

    with freeze_time(paused_at):
        pause_sla(instance=instance, reason=SlaInstance.State.PAUSED_REQUESTER)

    instance.refresh_from_db()
    clock = serialize_sla_clock(instance, later)
    assert clock["state"] == "paused"
    assert clock["due_at"] is None
    assert clock["remaining_seconds"] == 3600
    assert clock["overdue_seconds"] == 0


def test_pause_reason_change_does_not_consume_frozen_entitlement(
    basic_world: BasicWorld,
) -> None:
    paused_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    remapped_at = paused_at + timedelta(minutes=30)
    resumed_at = datetime(2026, 7, 27, 13, 0, tzinfo=UTC)
    instance = _instance(basic_world, due_at=paused_at + timedelta(hours=1))

    with freeze_time(paused_at):
        pause_sla(instance=instance, reason=SlaInstance.State.PAUSED_REQUESTER)
    with freeze_time(remapped_at):
        pause_sla(instance=instance, reason=SlaInstance.State.PAUSED_INTERNAL)
    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="internal_dependency_cleared")

    instance.refresh_from_db()
    assert instance.due_at == resumed_at + timedelta(hours=1)


def test_pause_freezes_business_entitlement_instead_of_closed_wall_time(
    basic_world: BasicWorld,
) -> None:
    friday_pause = datetime(2026, 7, 31, 14, 30, tzinfo=UTC)  # 16:30 local
    monday_due = datetime(2026, 8, 3, 7, 30, tzinfo=UTC)  # 09:30 local
    monday_resume = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)  # 13:00 local
    instance = _instance(basic_world, due_at=monday_due)

    with freeze_time(friday_pause):
        pause_sla(instance=instance, reason=SlaInstance.State.PAUSED_REQUESTER)
    with freeze_time(monday_resume):
        resume_sla(instance=instance, reason="requester_replied")

    instance.refresh_from_db()
    # Seeded calendar is open 08:00-17:00: 30 min Friday + 90 min Monday.
    assert instance.due_at == monday_resume + timedelta(hours=2)


def test_completion_after_deadline_records_completion_without_marking_sla_met(
    basic_world: BasicWorld,
) -> None:
    due_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    completed_at = due_at + timedelta(seconds=1)
    instance = _instance(basic_world, due_at=due_at)

    complete_sla(
        ticket=instance.ticket,
        kind=instance.kind,
        at=completed_at,
    )

    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED
    assert instance.breached_at == due_at
    assert instance.completed_at == completed_at


def test_completion_at_exact_deadline_uses_breached_boundary(
    basic_world: BasicWorld,
) -> None:
    due_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    instance = _instance(basic_world, due_at=due_at)

    complete_sla(ticket=instance.ticket, kind=instance.kind, at=due_at)

    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED
    assert instance.breached_at == due_at
    assert serialize_sla_clock(instance, due_at)["state"] == "breached"


def test_evaluator_at_exact_deadline_uses_breached_boundary(
    basic_world: BasicWorld,
) -> None:
    due_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    instance = _instance(basic_world, due_at=due_at)
    assert serialize_sla_clock(instance, due_at)["state"] == "breached"

    with freeze_time(due_at):
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED


def test_breached_completion_is_timestamped_once_and_stops_overdue_clock(
    basic_world: BasicWorld,
) -> None:
    due_at = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
    first_completion = due_at + timedelta(hours=1)
    later_retry = first_completion + timedelta(hours=1)
    display_now = later_retry + timedelta(hours=1)
    instance = _instance(
        basic_world,
        due_at=due_at,
        state=SlaInstance.State.BREACHED,
    )
    recorded_breach = due_at + timedelta(minutes=1)
    instance.breached_at = recorded_breach
    instance.save(update_fields=["breached_at"])

    complete_sla(
        ticket=instance.ticket,
        kind=instance.kind,
        at=first_completion,
    )
    complete_sla(
        ticket=instance.ticket,
        kind=instance.kind,
        at=later_retry,
    )

    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED
    assert instance.breached_at == recorded_breach
    assert instance.completed_at == first_completion
    assert serialize_sla_clock(instance, display_now)["overdue_seconds"] == 3600


def test_completion_cannot_turn_an_exhausted_paused_clock_into_met(
    basic_world: BasicWorld,
) -> None:
    due_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    paused_at = due_at + timedelta(minutes=1)
    resumed_at = due_at + timedelta(hours=1)
    instance = _instance(basic_world, due_at=due_at)

    with freeze_time(paused_at):
        pause_sla(instance=instance, reason=SlaInstance.State.PAUSED_REQUESTER)
    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="requester_replied")
        complete_sla(ticket=instance.ticket, kind=instance.kind, at=resumed_at)

    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED
    assert instance.completed_at == resumed_at


def test_resume_recovers_legacy_null_entitlement_from_pause_history(
    basic_world: BasicWorld,
) -> None:
    paused_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    due_at = paused_at + timedelta(hours=1)
    resumed_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    instance = _instance(
        basic_world,
        due_at=due_at,
        state=SlaInstance.State.PAUSED_REQUESTER,
    )
    history = SlaPauseHistory.objects.create(
        instance=instance,
        state=SlaInstance.State.PAUSED_REQUESTER,
        reason="legacy_pause",
    )
    SlaPauseHistory.objects.filter(pk=history.pk).update(at=paused_at)
    calendar = instance.policy.calendar
    calendar.weekday_hours = {"1": [{"start": "12:00", "end": "17:00"}]}
    calendar.holidays = []
    calendar.save(update_fields=["weekday_hours", "holidays"])

    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="requester_replied")

    instance.refresh_from_db()
    assert instance.due_at == resumed_at + timedelta(hours=1)
    assert instance.remaining_business_seconds is None


def test_resume_fails_closed_for_legacy_null_entitlement_without_history(
    basic_world: BasicWorld,
) -> None:
    resumed_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    instance = _instance(
        basic_world,
        due_at=resumed_at + timedelta(hours=1),
        state=SlaInstance.State.PAUSED_REQUESTER,
    )

    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="requester_replied")

    instance.refresh_from_db()
    assert instance.due_at == resumed_at
    assert instance.remaining_business_seconds == 0


def test_completion_fails_closed_for_legacy_paused_null_entitlement(
    basic_world: BasicWorld,
) -> None:
    completed_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    instance = _instance(
        basic_world,
        due_at=completed_at - timedelta(hours=1),
        state=SlaInstance.State.PAUSED_REQUESTER,
    )

    complete_sla(ticket=instance.ticket, kind=instance.kind, at=completed_at)

    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED
    assert instance.completed_at == completed_at


def test_data_migration_backfills_history_and_fails_closed_without_it(
    basic_world: BasicWorld,
) -> None:
    paused_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    with_history = _instance(
        basic_world,
        due_at=paused_at + timedelta(hours=1),
        state=SlaInstance.State.PAUSED_REQUESTER,
    )
    history = SlaPauseHistory.objects.create(
        instance=with_history,
        state=SlaInstance.State.PAUSED_REQUESTER,
        reason="legacy_pause",
    )
    SlaPauseHistory.objects.filter(pk=history.pk).update(at=paused_at)
    calendar = with_history.policy.calendar
    calendar.weekday_hours = {}
    calendar.holidays = ["2026-07-27"]
    calendar.save(update_fields=["weekday_hours", "holidays"])
    without_history = _instance(
        basic_world,
        due_at=paused_at + timedelta(hours=1),
        state=SlaInstance.State.PAUSED_INTERNAL,
    )

    migration = import_module("apps.sla.migrations.0004_backfill_paused_remaining_business_seconds")
    migration.backfill_paused_remaining_business_seconds(django_apps, None)

    with_history.refresh_from_db()
    without_history.refresh_from_db()
    assert with_history.remaining_business_seconds == 3600
    assert without_history.remaining_business_seconds == 0


def test_evaluator_rolls_back_all_transitions_when_one_update_fails(
    basic_world: BasicWorld,
) -> None:
    first = _instance(basic_world, due_at=timezone.now() - timedelta(seconds=2))
    second = _instance(basic_world, due_at=timezone.now() - timedelta(seconds=1))
    original_save = SlaInstance.save
    save_calls = 0

    def fail_second_save(
        instance: SlaInstance,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise RuntimeError("injected evaluator persistence failure")
        original_save(instance)

    with patch.object(SlaInstance, "save", autospec=True, side_effect=fail_second_save):
        with pytest.raises(RuntimeError, match="injected evaluator persistence failure"):
            evaluate_open_slas()

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.state == SlaInstance.State.ACTIVE
    assert second.state == SlaInstance.State.ACTIVE
    assert first.last_evaluated_at is None
    assert second.last_evaluated_at is None


@pytest.mark.django_db(transaction=True)
def test_evaluator_skips_an_instance_locked_by_a_concurrent_sweep(
    basic_world: BasicWorld,
) -> None:
    instance = _instance(basic_world, due_at=timezone.now() - timedelta(seconds=1))
    lock_acquired = Event()
    release_lock = Event()
    evaluation_finished = Event()
    evaluation_results: list[int] = []
    thread_errors: list[BaseException] = []

    def hold_instance_lock() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '2s'")
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                SlaInstance.objects.select_for_update().get(pk=instance.pk)
                lock_acquired.set()
                if not release_lock.wait(timeout=5):
                    raise TimeoutError("test did not release the SLA row lock")
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            close_old_connections()

    def run_evaluator() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '2s'")
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                evaluation_results.append(evaluate_open_slas())
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            evaluation_finished.set()
            close_old_connections()

    lock_thread = Thread(target=hold_instance_lock, daemon=True)
    evaluator_thread = Thread(target=run_evaluator, daemon=True)
    try:
        lock_thread.start()
        assert lock_acquired.wait(timeout=5)
        evaluator_thread.start()
        finished_while_locked = evaluation_finished.wait(timeout=1)
    finally:
        release_lock.set()
        lock_thread.join(timeout=5)
        evaluator_thread.join(timeout=5)

    assert not lock_thread.is_alive(), "instance-lock worker did not complete"
    assert not evaluator_thread.is_alive(), "evaluator worker did not complete"
    if thread_errors:
        raise thread_errors[0]
    assert not thread_errors
    assert finished_while_locked
    assert evaluation_results == [0]
    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.ACTIVE

    assert evaluate_open_slas() == 1
    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED
    breached_at = instance.breached_at

    assert evaluate_open_slas() == 0
    instance.refresh_from_db()
    assert instance.breached_at == breached_at


@pytest.mark.django_db(transaction=True)
def test_evaluator_skips_a_ticket_locked_by_an_independent_transaction(
    basic_world: BasicWorld,
) -> None:
    """A busy first ticket must not stall an unlocked ticket in the same batch."""
    instance = _instance(
        basic_world,
        due_at=timezone.now() - timedelta(seconds=1),
        ticket_id=UUID(int=1),
    )
    unlocked_instance = _instance(
        basic_world,
        due_at=timezone.now() - timedelta(seconds=1),
        ticket_id=UUID(int=2),
    )
    ticket_locked = Event()
    release_ticket = Event()
    evaluation_finished = Event()
    evaluation_results: list[int] = []
    thread_errors: list[BaseException] = []

    def hold_ticket_lock() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '2s'")
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                Ticket.objects.select_for_update().get(pk=instance.ticket_id)
                ticket_locked.set()
                if not release_ticket.wait(timeout=5):
                    raise TimeoutError("test did not release the ticket lock")
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            close_old_connections()

    def run_evaluator() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '2s'")
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                evaluation_results.append(evaluate_open_slas())
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            evaluation_finished.set()
            close_old_connections()

    lock_thread = Thread(target=hold_ticket_lock, daemon=True)
    evaluator_thread = Thread(target=run_evaluator, daemon=True)
    try:
        lock_thread.start()
        assert ticket_locked.wait(timeout=5)
        evaluator_thread.start()
        assert evaluation_finished.wait(timeout=3)
    finally:
        release_ticket.set()
        lock_thread.join(timeout=5)
        evaluator_thread.join(timeout=5)

    assert not lock_thread.is_alive(), "ticket-lock worker did not complete"
    assert not evaluator_thread.is_alive(), "evaluator worker did not complete"
    if thread_errors:
        raise thread_errors[0]
    assert thread_errors == []
    assert evaluation_results == [1]
    instance.refresh_from_db()
    unlocked_instance.refresh_from_db()
    assert instance.state == SlaInstance.State.ACTIVE
    assert instance.last_evaluated_at is None
    assert instance.ticket.custody_events.count() == 0
    assert unlocked_instance.state == SlaInstance.State.BREACHED
    assert unlocked_instance.last_evaluated_at is not None

    assert evaluate_open_slas() == 1
    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED


@pytest.mark.django_db(transaction=True)
def test_evaluator_does_not_skip_ticket_when_only_joined_status_is_locked(
    basic_world: BasicWorld,
) -> None:
    """The aggregate lock must not include the joined workflow status row."""
    instance = _instance(basic_world, due_at=timezone.now() - timedelta(seconds=1))
    status_locked = Event()
    release_status = Event()
    evaluation_finished = Event()
    evaluation_results: list[int] = []
    thread_errors: list[BaseException] = []

    def hold_status_lock() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '2s'")
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                Status.objects.select_for_update().get(pk=instance.ticket.status_id)
                status_locked.set()
                if not release_status.wait(timeout=5):
                    raise TimeoutError("test did not release the status lock")
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            close_old_connections()

    def run_evaluator() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '2s'")
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                evaluation_results.append(evaluate_open_slas())
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            evaluation_finished.set()
            close_old_connections()

    lock_thread = Thread(target=hold_status_lock, daemon=True)
    evaluator_thread = Thread(target=run_evaluator, daemon=True)
    try:
        lock_thread.start()
        assert status_locked.wait(timeout=5)
        evaluator_thread.start()
        assert evaluation_finished.wait(timeout=3)
    finally:
        release_status.set()
        lock_thread.join(timeout=5)
        evaluator_thread.join(timeout=5)

    assert not lock_thread.is_alive(), "status-lock worker did not complete"
    assert not evaluator_thread.is_alive(), "evaluator worker did not complete"
    if thread_errors:
        raise thread_errors[0]
    assert thread_errors == []
    assert evaluation_results == [1]
    instance.refresh_from_db()
    assert instance.state == SlaInstance.State.BREACHED
    assert instance.last_evaluated_at is not None


class TestSlaTransitionLockOrder(TransactionTestCase):
    """Exercise evaluator and workflow locks on independent PostgreSQL connections."""

    def setUp(self) -> None:
        if connection.vendor != "postgresql":
            self.skipTest("This lock-order regression requires PostgreSQL.")

        seed_workflow()
        seed_sla()
        region = django_apps.get_model("organisations", "Region").objects.create(
            code="LCK", name="Lock order"
        )
        office = Office.objects.create(region=region, code="LCK-1", name="Lock office")
        service = Service.objects.create(code="LCK-SVC", name="Lock service", domain="operational")
        request_type = service.request_types.create(
            code="LCK-RT", name="Lock request", default_priority="P3"
        )
        contact = Contact.objects.create(full_name="Lock Tester", email="lock@example.test")
        self.actor = django_apps.get_model("identity_access", "User").objects.create(
            username="lock-agent",
            keycloak_subject="lock-agent-subject",
            keycloak_groups=["ops-agents"],
            office=office,
        )
        self.actor._groups = ["ops-agents"]
        assistant_master, _ = Role.objects.get_or_create(
            keycloak_role="assistant-master",
            defaults={
                "name": "Assistant Master",
                "scopes": [{"domain": "operational"}],
            },
        )
        UserRole.objects.create(
            user=self.actor,
            role=assistant_master,
            office=office,
        )
        ticket = ticket_services.create_ticket(
            domain="operational",
            title="Lock order regression",
            description="",
            requester=contact,
            service=service,
            request_type=request_type,
            office=office,
            channel="web",
        )
        ticket = ticket_services.transition_ticket(
            ticket_id=ticket.id,
            actor=self.actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="triage",
        )
        self.ticket = ticket_services.transition_ticket(
            ticket_id=ticket.id,
            actor=self.actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="in_progress",
        )
        policy = SlaPolicy.objects.get(domain="operational", priority="P3")
        policy.resolution_minutes = 10
        policy.escalation_percent = 50
        policy.save(update_fields=["resolution_minutes", "escalation_percent"])
        self.instance = SlaInstance.objects.create(
            ticket=self.ticket,
            policy=policy,
            kind="resolution",
            state=SlaInstance.State.ACTIVE,
            started_at=timezone.now() - timedelta(minutes=11),
            due_at=timezone.now() - timedelta(minutes=1),
        )

    def test_transition_and_evaluator_complete_without_opposite_row_locks(self) -> None:
        """A transition cannot deadlock with an escalation custody write."""
        evaluator_first_lock = Event()
        transition_ticket_locked = Event()
        start = Event()
        errors: list[BaseException] = []
        results: list[int] = []
        evaluator_first_table: list[str] = []

        def is_lock_query(sql: str, table: str) -> bool:
            return "FOR UPDATE" in sql.upper() and f'FROM "{table}"' in sql

        def run_evaluator() -> None:
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '2s'")
                        cursor.execute("SET LOCAL statement_timeout = '5s'")
                    with connection.execute_wrapper(evaluator_wrapper):
                        if not start.wait(timeout=5):
                            raise TimeoutError("evaluator start was not released")
                        results.append(evaluate_open_slas())
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        def evaluator_wrapper(execute, sql, params, many, context):
            if not evaluator_first_table and (
                is_lock_query(sql, "sla_instance") or is_lock_query(sql, "ticket")
            ):
                table = "sla_instance" if is_lock_query(sql, "sla_instance") else "ticket"
                result = execute(sql, params, many, context)
                evaluator_first_table.append(table)
                evaluator_first_lock.set()
                if table == "sla_instance" and not transition_ticket_locked.wait(timeout=5):
                    raise TimeoutError("transition did not acquire its ticket lock")
                return result
            return execute(sql, params, many, context)

        def run_transition() -> None:
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '2s'")
                        cursor.execute("SET LOCAL statement_timeout = '5s'")
                    with connection.execute_wrapper(transition_wrapper):
                        if not start.wait(timeout=5):
                            raise TimeoutError("transition start was not released")
                        ticket_services.transition_ticket(
                            ticket_id=self.ticket.id,
                            actor=self.actor,
                            expected_updated_at=self.ticket.updated_at,
                            to_status_code="resolved",
                            resolution_code="INFO_PROVIDED",
                            resolution_summary="Resolved during lock-order regression.",
                        )
            except BaseException as exc:
                errors.append(exc)
            finally:
                close_old_connections()

        def transition_wrapper(execute, sql, params, many, context):
            if is_lock_query(sql, "ticket") and not transition_ticket_locked.is_set():
                if not evaluator_first_lock.wait(timeout=5):
                    raise TimeoutError("evaluator did not attempt its first row lock")
                result = execute(sql, params, many, context)
                transition_ticket_locked.set()
                return result
            return execute(sql, params, many, context)

        evaluator = Thread(target=run_evaluator, daemon=True)
        transition = Thread(target=run_transition, daemon=True)
        try:
            evaluator.start()
            transition.start()
            start.set()
        finally:
            start.set()
            evaluator.join(timeout=10)
            transition.join(timeout=10)

        assert not evaluator.is_alive(), "evaluator did not complete"
        assert not transition.is_alive(), "transition did not complete"
        if errors:
            raise errors[0]
        assert errors == []
        assert evaluator_first_table == ["ticket"]
        assert results == [1]

        self.ticket.refresh_from_db()
        self.instance.refresh_from_db()
        assert self.ticket.status.code == "resolved"
        assert self.instance.state == SlaInstance.State.BREACHED
        assert (
            self.ticket.custody_events.filter(
                source_process="sla.escalation", source_record_id=str(self.instance.id)
            ).count()
            == 1
        )
        assert verify_custody_chain(self.ticket)
