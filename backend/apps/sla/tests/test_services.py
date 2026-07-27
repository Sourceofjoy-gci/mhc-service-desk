"""Tests for SLA business calendar and instance state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.audit.models import AuditEvent
from apps.identity_access.models import User
from apps.sla.models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy
from apps.sla.services import (
    add_business_seconds,
    complete_sla,
    restart_resolution_sla,
    sync_slas_for_transition,
)
from apps.tickets import services as ticket_services
from apps.tickets.models import OutboxEvent, Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


@pytest.fixture
def calendar():
    return BusinessCalendar.objects.create(
        name="Test calendar",
        timezone="UTC",
        weekday_hours={
            "1": [{"start": "09:00", "end": "17:00"}],
            "2": [{"start": "09:00", "end": "17:00"}],
            "3": [],
            "4": [{"start": "09:00", "end": "13:00"}],
            "5": [{"start": "09:00", "end": "17:00"}],
            "6": [],
            "7": [],
        },
        holidays=[],
        is_default=True,
    )


def test_zero_seconds_returns_same_instant(calendar):
    start = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)  # Monday 10:00
    assert add_business_seconds(start, 0, calendar) == start


def test_skips_closed_days(calendar):
    # Wednesday 2026-07-22 is closed
    start = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    end = add_business_seconds(start, 60, calendar)
    # Should land on Thursday 2026-07-23 at 09:01
    assert end.weekday() == 3
    assert end.hour == 9
    assert end.minute == 1


def test_skips_holidays(calendar):
    calendar.holidays = ["2026-07-23"]
    calendar.save()
    start = datetime(2026, 7, 22, 16, 0, tzinfo=timezone.utc)  # Wed 16:00
    end = add_business_seconds(start, 60 * 60, calendar)  # +1h
    # Wednesday 16:00 -> 17:00 is closed; Thursday is a holiday.
    # The next business hour runs Friday 09:00 -> Friday 10:00.
    assert end.weekday() == 4
    assert (end.hour, end.minute) == (10, 0)


def test_within_day_addition(calendar):
    start = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)  # Monday 09:00
    end = add_business_seconds(start, 60 * 30, calendar)  # +30 minutes
    assert (end.hour, end.minute) == (9, 30)


def test_spans_lunch(calendar):
    # Thursday has 09:00-13:00 (4 hours). Start at 12:00, add 3h.
    start = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)  # Thursday
    end = add_business_seconds(start, 60 * 60 * 3, calendar)  # +3h
    # Only 1h remains Thursday, then 2h on Friday morning
    assert end.weekday() == 4
    assert (end.hour, end.minute) == (11, 0)


def _ticket(basic_world, *, domain="operational", status_code="in_progress"):
    service = (
        basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    )
    return Ticket.objects.create(
        number=f"{domain[:2].upper()}-202607-{Ticket.objects.count() + 992001:06d}",
        domain=domain,
        title="SLA lifecycle",
        status=Status.objects.get(domain=domain, code=status_code),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _instance(ticket, *, kind="resolution", state="active"):
    policy = SlaPolicy.objects.get(domain=ticket.domain, priority=ticket.priority)
    return SlaInstance.objects.create(
        ticket=ticket,
        policy=policy,
        kind=kind,
        state=state,
        due_at=ticket.created_at + policy.resolution_minutes * timedelta(minutes=1),
    )


def test_first_outbound_agent_message_completes_first_response_once(basic_world):
    ticket = _ticket(basic_world)
    instance = _instance(ticket, kind="first_response")

    ticket_services.add_message(
        ticket=ticket,
        direction="outbound",
        body_text="We are investigating.",
        actor_subject="agent-1",
    )

    ticket.refresh_from_db()
    instance.refresh_from_db()
    assert ticket.first_responded_at is not None
    assert instance.state == "met"
    assert instance.completed_at == ticket.first_responded_at

    first_response_at = ticket.first_responded_at
    ticket_services.add_message(
        ticket=ticket,
        direction="outbound",
        body_text="A later update.",
        actor_subject="agent-1",
    )
    ticket.refresh_from_db()
    instance.refresh_from_db()
    assert ticket.first_responded_at == first_response_at
    assert instance.completed_at == first_response_at


@pytest.mark.parametrize(
    ("domain", "to_code", "expected"),
    [
        ("operational", "waiting_requester", "paused_requester"),
        ("operational", "waiting_internal", "paused_internal"),
        ("operational", "waiting_it", "paused_it"),
        ("it", "waiting_user", "paused_requester"),
        ("it", "waiting_vendor", "paused_internal"),
        ("it", "waiting_change", "paused_internal"),
    ],
)
def test_waiting_transition_pauses_active_slas(
    basic_world,
    domain,
    to_code,
    expected,
):
    ticket = _ticket(basic_world, domain=domain)
    instance = _instance(ticket)

    sync_slas_for_transition(
        ticket=ticket,
        from_code="in_progress",
        to_code=to_code,
        actor_subject="agent-1",
    )

    instance.refresh_from_db()
    history = SlaPauseHistory.objects.get(instance=instance)
    assert instance.state == expected
    assert history.state == expected
    assert history.actor_subject == "agent-1"


def test_leaving_waiting_state_resumes_sla_and_records_history(basic_world):
    ticket = _ticket(basic_world)
    instance = _instance(ticket, state="paused_requester")

    sync_slas_for_transition(
        ticket=ticket,
        from_code="waiting_requester",
        to_code="in_progress",
        actor_subject="agent-1",
    )

    instance.refresh_from_db()
    history = SlaPauseHistory.objects.get(instance=instance)
    assert instance.state == "active"
    assert history.state == "active"
    assert history.actor_subject == "agent-1"


def test_resolution_completes_active_clock_but_preserves_breach(basic_world):
    ticket = _ticket(basic_world)
    active = _instance(ticket)
    at = ticket.created_at + timedelta(hours=1)

    complete_sla(ticket=ticket, kind="resolution", at=at)

    active.refresh_from_db()
    assert active.state == "met"
    assert active.completed_at == at

    active.state = "breached"
    active.completed_at = None
    active.breached_at = at
    active.save(update_fields=["state", "completed_at", "breached_at"])
    complete_sla(ticket=ticket, kind="resolution", at=at + timedelta(minutes=1))
    active.refresh_from_db()
    assert active.state == "breached"
    assert active.completed_at is None


def test_reopen_restarts_existing_resolution_clock_from_reopened_at(basic_world):
    ticket = _ticket(basic_world, status_code="reopened")
    reopened_at = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    ticket.reopened_at = reopened_at
    ticket.save(update_fields=["reopened_at"])
    instance = _instance(ticket, state="met")
    instance.completed_at = reopened_at - timedelta(hours=1)
    instance.breached_at = reopened_at - timedelta(hours=2)
    instance.breach_reason = "Prior breach"
    instance.save(
        update_fields=["completed_at", "breached_at", "breach_reason"]
    )

    restarted = restart_resolution_sla(ticket=ticket, at=reopened_at)

    assert restarted.id == instance.id
    assert SlaInstance.objects.filter(ticket=ticket, kind="resolution").count() == 1
    assert restarted.started_at == reopened_at
    assert restarted.due_at > reopened_at
    assert restarted.state == "active"
    assert restarted.completed_at is None
    assert restarted.breached_at is None
    assert restarted.breach_reason == ""


def test_transition_service_synchronizes_pause_without_losing_task_four_events(
    basic_world,
):
    actor = User.objects.create(
        username="sla-agent",
        keycloak_subject="sla-agent",
        keycloak_groups=["ops-agents"],
    )
    actor._groups = ["ops-agents"]
    ticket = _ticket(basic_world)
    instance = _instance(ticket)

    updated = ticket_services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="waiting_requester",
    )

    instance.refresh_from_db()
    assert updated.status.code == "waiting_requester"
    assert instance.state == "paused_requester"
    assert updated.transition_history.count() == 1
    assert AuditEvent.objects.filter(
        object_id=str(updated.id), action="ticket.transitioned"
    ).count() == 1
    assert OutboxEvent.objects.filter(
        aggregate_id=str(updated.id), event_type="ticket.transitioned"
    ).count() == 1
