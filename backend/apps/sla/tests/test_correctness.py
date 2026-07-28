"""Regression coverage for SLA entitlement and evaluator consistency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from threading import Event, Thread
from typing import TypedDict
from unittest.mock import patch

import pytest
from django.apps import apps as django_apps
from django.db import close_old_connections, transaction
from django.utils import timezone
from freezegun import freeze_time

from apps.catalogue.models import Service
from apps.contacts.models import Contact
from apps.organisations.models import Office
from apps.sla.models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy
from apps.sla.serializers import serialize_sla_clock
from apps.sla.services import (
    add_business_seconds,
    business_seconds_between,
    complete_sla,
    evaluate_open_slas,
    pause_sla,
    resume_sla,
)
from apps.tickets.models import Ticket
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
        weekday_hours={
            str(day): [{"start": "08:00", "end": "17:00"}]
            for day in range(1, 6)
        },
        holidays=holidays or [],
    )


def test_add_business_seconds_uses_calendar_local_timezone() -> None:
    calendar = _mbabane_calendar()
    start = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)  # 08:00 in Mbabane

    assert add_business_seconds(start, 3600, calendar) == datetime(
        2026, 7, 27, 7, 0, tzinfo=UTC
    )


def test_add_business_seconds_applies_holiday_to_calendar_local_date() -> None:
    calendar = _mbabane_calendar(holidays=["2026-07-28"])
    start = datetime(2026, 7, 27, 14, 30, tzinfo=UTC)  # 16:30 local

    assert add_business_seconds(start, 3600, calendar) == datetime(
        2026, 7, 29, 6, 30, tzinfo=UTC
    )


def test_business_seconds_between_uses_calendar_local_slots() -> None:
    calendar = _mbabane_calendar()
    start = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    end = datetime(2026, 7, 27, 7, 0, tzinfo=UTC)

    assert business_seconds_between(start, end, calendar) == 3600


def _ticket(basic_world: BasicWorld) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
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
) -> SlaInstance:
    ticket = _ticket(basic_world)
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
    without_history = _instance(
        basic_world,
        due_at=paused_at + timedelta(hours=1),
        state=SlaInstance.State.PAUSED_INTERNAL,
    )

    migration = import_module(
        "apps.sla.migrations.0004_backfill_paused_remaining_business_seconds"
    )
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
            evaluation_results.append(evaluate_open_slas())
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            evaluation_finished.set()
            close_old_connections()

    lock_thread = Thread(target=hold_instance_lock)
    evaluator_thread = Thread(target=run_evaluator)
    lock_thread.start()
    assert lock_acquired.wait(timeout=5)
    evaluator_thread.start()
    finished_while_locked = evaluation_finished.wait(timeout=1)
    release_lock.set()
    lock_thread.join(timeout=5)
    evaluator_thread.join(timeout=5)

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
