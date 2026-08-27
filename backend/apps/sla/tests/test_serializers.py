"""Consumer-facing SLA clock serialization tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.sla.models import SlaInstance, SlaPolicy
from apps.sla.serializers import serialize_sla_clock, serialize_sla_clocks
from apps.tickets.models import Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)


def _ticket(basic_world) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 991001:06d}",
        domain="operational",
        title="SLA clock",
        status=Status.objects.get(domain="operational", code="in_progress"),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _instance(basic_world, *, state: str, due_at) -> SlaInstance:
    ticket = _ticket(basic_world)
    policy = SlaPolicy.objects.get(domain="operational", priority="P3")
    return SlaInstance.objects.create(
        ticket=ticket,
        policy=policy,
        kind="first_response",
        state=state,
        started_at=NOW - timedelta(hours=1),
        due_at=due_at,
    )


def test_absent_sla_instance_is_not_started(basic_world):
    ticket = _ticket(basic_world)

    assert serialize_sla_clocks(ticket, now=NOW) == {
        "first_response": {
            "state": "not_started",
            "due_at": None,
            "remaining_seconds": 0,
            "overdue_seconds": 0,
        },
        "resolution": {
            "state": "not_started",
            "due_at": None,
            "remaining_seconds": 0,
            "overdue_seconds": 0,
        },
    }


def test_active_future_sla_is_running_with_exact_remaining_duration(basic_world):
    instance = _instance(
        basic_world,
        state="active",
        due_at=NOW + timedelta(hours=1),
    )

    assert serialize_sla_clock(instance, NOW) == {
        "state": "running",
        "due_at": "2026-07-27T10:00:00Z",
        "remaining_seconds": 3600,
        "overdue_seconds": 0,
    }


@pytest.mark.parametrize(
    ("persisted_state", "expected_state", "due_offset", "remaining", "overdue"),
    [
        ("paused_requester", "paused", timedelta(minutes=30), 1800, 0),
        ("paused_internal", "paused", -timedelta(minutes=30), 0, 0),
        ("paused_it", "paused", timedelta(0), 0, 0),
        ("met", "met", -timedelta(minutes=5), 0, 0),
        ("breached", "breached", -timedelta(minutes=5), 0, 300),
        ("active", "breached", -timedelta(minutes=5), 0, 300),
    ],
)
def test_sla_states_are_normalized_without_negative_durations(
    basic_world,
    persisted_state,
    expected_state,
    due_offset,
    remaining,
    overdue,
):
    instance = _instance(
        basic_world,
        state=persisted_state,
        due_at=NOW + due_offset,
    )

    clock = serialize_sla_clock(instance, NOW)

    assert clock["state"] == expected_state
    assert clock["remaining_seconds"] == remaining
    assert clock["overdue_seconds"] == overdue
    assert clock["remaining_seconds"] >= 0
    assert clock["overdue_seconds"] >= 0
