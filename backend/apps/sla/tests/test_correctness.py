"""Regression coverage for SLA entitlement and evaluator consistency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import TypedDict
from unittest.mock import patch

import pytest
from django.db import close_old_connections, transaction
from django.utils import timezone
from freezegun import freeze_time

from apps.catalogue.models import Service
from apps.contacts.models import Contact
from apps.organisations.models import Office
from apps.sla.models import SlaInstance, SlaPolicy
from apps.sla.serializers import serialize_sla_clock
from apps.sla.services import (
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
    friday_pause = datetime(2026, 7, 31, 16, 30, tzinfo=UTC)
    monday_due = datetime(2026, 8, 3, 9, 30, tzinfo=UTC)
    monday_resume = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)
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
