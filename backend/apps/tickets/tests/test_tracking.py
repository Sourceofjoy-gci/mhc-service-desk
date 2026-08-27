from __future__ import annotations

import pytest

from apps.tickets import services
from apps.tickets.tracking import (
    TrackingStatus,
    build_tracking_progress,
    build_tracking_projection,
    tracking_status_for,
)
from apps.workflow.models import Status, TransitionHistory


@pytest.fixture
def tracking_ticket(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="Tracking projection",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
        channel="call",
    )
    previous = Status.objects.get(domain="operational", code="new")
    for code in ("triage", "in_progress", "quality_review"):
        target = Status.objects.get(domain="operational", code=code)
        TransitionHistory.objects.create(
            ticket=ticket,
            from_status=previous,
            to_status=target,
            actor_subject="tracking-agent",
        )
        previous = target
    return ticket


@pytest.mark.parametrize(
    ("code", "terminal", "expected"),
    [
        ("new", False, "Submitted"),
        ("triage", False, "Acknowledged"),
        ("assigned", False, "Assigned"),
        ("diagnosing", False, "In Progress"),
        ("waiting_requester", False, "Awaiting Information"),
        ("escalated", False, "Escalated"),
        ("resolved", False, "Resolved"),
        ("closed", True, "Closed"),
        ("duplicate", True, "Closed"),
        ("reopened", False, "Reopened"),
    ],
)
def test_tracking_status_mapping_is_stable(code, terminal, expected):
    assert tracking_status_for({"code": code, "is_terminal": terminal}) == expected


def test_tracking_status_contract_contains_exactly_the_nine_supported_labels():
    assert [status.value for status in TrackingStatus] == [
        "Submitted",
        "Acknowledged",
        "Assigned",
        "In Progress",
        "Awaiting Information",
        "Escalated",
        "Resolved",
        "Closed",
        "Reopened",
    ]


def test_unknown_statuses_fail_into_a_supported_active_or_terminal_label():
    assert tracking_status_for({"code": "custom_active", "is_terminal": False}) == (
        TrackingStatus.IN_PROGRESS
    )
    assert tracking_status_for({"code": "custom_terminal", "is_terminal": True}) == (
        TrackingStatus.CLOSED
    )


@pytest.mark.django_db
def test_tracking_progress_collapses_adjacent_internal_states_without_leaking_details(
    tracking_ticket,
):
    ticket = tracking_ticket
    created = ticket.custody_events.get(sequence=1)

    progress = build_tracking_progress(ticket)

    assert progress == [
        {"status": "Submitted", "occurred_at": created.occurred_at},
        {
            "status": "Acknowledged",
            "occurred_at": ticket.transition_history.get(to_status__code="triage").occurred_at,
        },
        {
            "status": "In Progress",
            "occurred_at": ticket.transition_history.get(to_status__code="in_progress").occurred_at,
        },
    ]
    assert all(set(item) == {"status", "occurred_at"} for item in progress)


@pytest.mark.django_db
def test_tracking_projection_uses_latest_internal_transition_for_status_update(
    tracking_ticket,
):
    projection = build_tracking_projection(tracking_ticket)

    assert projection["progress"][-1]["occurred_at"] == (
        tracking_ticket.transition_history.get(to_status__code="in_progress").occurred_at
    )
    assert projection["status_updated_at"] == (
        tracking_ticket.transition_history.get(to_status__code="quality_review").occurred_at
    )
