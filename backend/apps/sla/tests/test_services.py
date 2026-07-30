"""Tests for SLA business calendar and instance state."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from apps.audit.models import AuditEvent
from apps.identity_access.models import User
from apps.sla.models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy
from apps.sla.services import (
    add_business_seconds,
    complete_sla,
    evaluate_open_slas,
    pause_sla,
    restart_resolution_sla,
    resume_sla,
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
    start = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)  # Monday 10:00
    assert add_business_seconds(start, 0, calendar) == start


def test_skips_closed_days(calendar):
    # Wednesday 2026-07-22 is closed
    start = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    end = add_business_seconds(start, 60, calendar)
    # Should land on Thursday 2026-07-23 at 09:01
    assert end.weekday() == 3
    assert end.hour == 9
    assert end.minute == 1


def test_skips_holidays(calendar):
    calendar.holidays = ["2026-07-23"]
    calendar.save()
    start = datetime(2026, 7, 22, 16, 0, tzinfo=UTC)  # Wed 16:00
    end = add_business_seconds(start, 60 * 60, calendar)  # +1h
    # Wednesday 16:00 -> 17:00 is closed; Thursday is a holiday.
    # The next business hour runs Friday 09:00 -> Friday 10:00.
    assert end.weekday() == 4
    assert (end.hour, end.minute) == (10, 0)


def test_within_day_addition(calendar):
    start = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)  # Monday 09:00
    end = add_business_seconds(start, 60 * 30, calendar)  # +30 minutes
    assert (end.hour, end.minute) == (9, 30)


def test_spans_lunch(calendar):
    # Thursday has 09:00-13:00 (4 hours). Start at 12:00, add 3h.
    start = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)  # Thursday
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


def _set_resolution_escalation_threshold(
    instance: SlaInstance,
    *,
    started_at: datetime,
    resolution_minutes: int = 10,
) -> datetime:
    """Configure a hand-checkable 90% business-time crossing for one SLA."""
    policy = instance.policy
    policy.resolution_minutes = resolution_minutes
    policy.escalation_percent = 90
    policy.save(update_fields=["resolution_minutes", "escalation_percent"])
    threshold_time = started_at + timedelta(minutes=9)
    instance.started_at = started_at
    instance.due_at = started_at + timedelta(minutes=resolution_minutes)
    instance.save(update_fields=["started_at", "due_at"])
    return threshold_time


def test_evaluator_records_one_system_custody_escalation_at_exact_business_threshold(
    basic_world,
):
    """Dropping the threshold recorder would lose the ticket's escalation history."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    threshold_time = _set_resolution_escalation_threshold(
        instance,
        started_at=started_at,
    )

    with freeze_time(threshold_time):
        evaluate_open_slas()
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at == threshold_time
    events = ticket.custody_events.filter(event_type="escalated")
    assert events.count() == 1
    event = events.get()
    assert event.actor_kind == "system"
    assert event.actor_subject == "sla:evaluator"
    assert event.source_process == "sla.escalation"
    assert event.source_record_type == "sla_instance"
    assert event.source_record_id == str(instance.id)
    assert event.reason == "resolution SLA crossed the 90% escalation threshold"
    assert event.previous_status == {"code": "in_progress", "label": "In Progress"}
    assert event.new_status == {"code": "in_progress", "label": "In Progress"}

    audit = AuditEvent.objects.get(object_id=str(ticket.id), action="ticket.escalated")
    assert audit.payload["before"] == {
        "sla": {
            "instance_id": str(instance.id),
            "kind": "resolution",
            "escalation_notified_at": None,
        }
    }
    assert audit.payload["after"] == {
        "sla": {
            "instance_id": str(instance.id),
            "kind": "resolution",
            "escalation_notified_at": "2026-07-27 06:09:00+00:00",
        }
    }
    assert AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.escalated"
    ).count() == 1


def test_evaluator_does_not_escalate_before_business_time_threshold(basic_world):
    """Changing the >= threshold boundary would create a premature custody record."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    threshold_time = _set_resolution_escalation_threshold(
        instance,
        started_at=started_at,
    )

    with freeze_time(threshold_time - timedelta(seconds=1)):
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at is None
    assert ticket.custody_events.filter(event_type="escalated").count() == 0
    assert AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.escalated"
    ).count() == 0


def test_evaluator_respects_microseconds_before_at_and_after_threshold(basic_world):
    """Flooring remaining seconds would escalate 499 microseconds before 90%."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 6, 0, 0, 500000, tzinfo=UTC)
    threshold_time = _set_resolution_escalation_threshold(
        instance,
        started_at=started_at,
    )

    with freeze_time(threshold_time - timedelta(microseconds=1)):
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at is None
    assert ticket.custody_events.filter(event_type="escalated").count() == 0

    with freeze_time(threshold_time):
        evaluate_open_slas()
    with freeze_time(threshold_time + timedelta(microseconds=1)):
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at == threshold_time
    assert ticket.custody_events.filter(event_type="escalated").count() == 1


def test_evaluator_does_not_escalate_paused_sla(basic_world):
    """Removing the active-state guard would escalate a clock that is frozen."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket, state=SlaInstance.State.PAUSED_REQUESTER)
    started_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    threshold_time = _set_resolution_escalation_threshold(
        instance,
        started_at=started_at,
    )

    with freeze_time(threshold_time + timedelta(minutes=1)):
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at is None
    assert ticket.custody_events.filter(event_type="escalated").count() == 0


def test_evaluator_excludes_business_time_while_sla_is_paused_then_resumed(
    basic_world,
):
    """Using the original start after resume would escalate during frozen time."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    _set_resolution_escalation_threshold(instance, started_at=started_at)
    paused_at = started_at + timedelta(minutes=2)
    resumed_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)

    with freeze_time(paused_at):
        pause_sla(
            instance=instance,
            reason=SlaInstance.State.PAUSED_REQUESTER,
        )
    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="requester_replied")
    with freeze_time(resumed_at + timedelta(minutes=6, seconds=59)):
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at is None
    assert ticket.custody_events.filter(event_type="escalated").count() == 0

    threshold_time = resumed_at + timedelta(minutes=7)
    with freeze_time(threshold_time):
        evaluate_open_slas()
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at == threshold_time
    assert ticket.custody_events.filter(event_type="escalated").count() == 1


def test_evaluator_respects_microseconds_after_pause_and_resume(basic_world):
    """Flooring resumed remaining time would escalate one microsecond too early."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 6, 0, 0, 500000, tzinfo=UTC)
    _set_resolution_escalation_threshold(instance, started_at=started_at)
    paused_at = started_at + timedelta(minutes=2, microseconds=1)
    resumed_at = datetime(2026, 7, 27, 10, 0, 0, 500000, tzinfo=UTC)

    with freeze_time(paused_at):
        pause_sla(
            instance=instance,
            reason=SlaInstance.State.PAUSED_REQUESTER,
        )
    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="requester_replied")

    threshold_time = resumed_at + timedelta(seconds=419, microseconds=999999)
    instance.refresh_from_db()
    assert instance.due_at == threshold_time + timedelta(seconds=60)
    with freeze_time(threshold_time - timedelta(microseconds=1)):
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at is None
    assert ticket.custody_events.filter(event_type="escalated").count() == 0

    with freeze_time(threshold_time):
        evaluate_open_slas()
    with freeze_time(threshold_time + timedelta(microseconds=1)):
        evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at == threshold_time
    assert ticket.custody_events.filter(event_type="escalated").count() == 1


def test_resume_preserves_fractional_entitlement_across_slot_boundary_and_remaps(
    basic_world,
):
    """Using the later pause or whole seconds would lose the original entitlement."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 14, 59, 0, 500000, tzinfo=UTC)
    _set_resolution_escalation_threshold(
        instance,
        started_at=started_at,
        resolution_minutes=2,
    )
    instance.due_at = datetime(2026, 7, 28, 6, 1, 0, 500000, tzinfo=UTC)
    instance.save(update_fields=["due_at"])
    paused_at = datetime(2026, 7, 27, 14, 59, 30, 500001, tzinfo=UTC)
    remapped_at = datetime(2026, 7, 27, 15, 0, 0, 100000, tzinfo=UTC)
    resumed_at = datetime(2026, 7, 28, 7, 0, tzinfo=UTC)

    with freeze_time(paused_at):
        pause_sla(
            instance=instance,
            reason=SlaInstance.State.PAUSED_REQUESTER,
        )
    with freeze_time(remapped_at):
        pause_sla(
            instance=instance,
            reason=SlaInstance.State.PAUSED_INTERNAL,
        )
    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="internal_dependency_cleared")

    instance.refresh_from_db()
    assert instance.due_at == datetime(
        2026,
        7,
        28,
        7,
        1,
        29,
        999999,
        tzinfo=UTC,
    )

def test_resume_uses_frozen_microseconds_after_calendar_changes(basic_world):
    """Recomputing a pause under edited calendar rules would lose entitlement."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 6, 0, 0, 500000, tzinfo=UTC)
    _set_resolution_escalation_threshold(instance, started_at=started_at)
    paused_at = started_at + timedelta(minutes=2, microseconds=1)
    resumed_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)

    with freeze_time(paused_at):
        pause_sla(
            instance=instance,
            reason=SlaInstance.State.PAUSED_REQUESTER,
        )

    instance.refresh_from_db()
    assert instance.remaining_business_microseconds == 479999999
    calendar = instance.policy.calendar
    calendar.timezone = "UTC"
    calendar.holidays = ["2026-07-27"]
    calendar.save(update_fields=["timezone", "holidays"])

    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="requester_replied")

    instance.refresh_from_db()
    assert instance.due_at == datetime(2026, 7, 28, 8, 7, 59, 999999, tzinfo=UTC)
    assert instance.remaining_business_microseconds is None


def test_resume_uses_frozen_microseconds_when_pause_histories_share_timestamp(
    basic_world,
):
    """The current paused field, not UUID ordering, must determine entitlement."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 6, 0, 0, 500000, tzinfo=UTC)
    _set_resolution_escalation_threshold(instance, started_at=started_at)
    paused_at = started_at + timedelta(minutes=2, microseconds=1)
    remapped_at = paused_at + timedelta(minutes=1)
    resumed_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)

    with freeze_time(paused_at):
        pause_sla(
            instance=instance,
            reason=SlaInstance.State.PAUSED_REQUESTER,
        )
    with freeze_time(remapped_at):
        pause_sla(
            instance=instance,
            reason=SlaInstance.State.PAUSED_INTERNAL,
        )
    SlaPauseHistory.objects.filter(instance=instance).update(at=remapped_at)

    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="internal_dependency_cleared")

    instance.refresh_from_db()
    assert instance.due_at == datetime(2026, 7, 27, 10, 7, 59, 999999, tzinfo=UTC)
    assert instance.remaining_business_microseconds is None


def test_resume_legacy_integer_entitlement_when_exact_field_is_null(basic_world):
    """Legacy paused rows retain their persisted whole-second fallback."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket, state=SlaInstance.State.PAUSED_REQUESTER)
    instance.remaining_business_seconds = 120
    instance.remaining_business_microseconds = None
    instance.save(
        update_fields=[
            "remaining_business_seconds",
            "remaining_business_microseconds",
        ]
    )
    resumed_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)

    with freeze_time(resumed_at):
        resume_sla(instance=instance, reason="legacy_resume")

    instance.refresh_from_db()
    assert instance.due_at == resumed_at + timedelta(minutes=2)
    assert instance.remaining_business_microseconds is None


def test_resume_recovers_legacy_pause_at_same_instant_as_resume(basic_world):
    """A same-instant post-resume pause must not disappear from legacy recovery."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    instance.due_at = at + timedelta(hours=1)
    instance.save(update_fields=["due_at"])

    with freeze_time(at):
        pause_sla(instance=instance, reason=SlaInstance.State.PAUSED_REQUESTER)
        resume_sla(instance=instance, reason="requester_replied")
        pause_sla(instance=instance, reason=SlaInstance.State.PAUSED_INTERNAL)
    SlaInstance.objects.filter(pk=instance.pk).update(
        remaining_business_microseconds=None,
        remaining_business_seconds=None,
    )

    with freeze_time(at):
        resume_sla(instance=instance, reason="legacy_retry")

    instance.refresh_from_db()
    assert instance.due_at == at + timedelta(hours=1)


def test_resume_legacy_recovery_prefers_pause_after_last_resume(basic_world):
    """An older same-instant pause must not over-grant a later current pause."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket, state=SlaInstance.State.PAUSED_REQUESTER)
    resumed_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    current_pause_at = resumed_at + timedelta(minutes=15)
    legacy_retry_at = datetime(2026, 7, 27, 14, 0, tzinfo=UTC)
    calendar = instance.policy.calendar
    calendar.timezone = "UTC"
    calendar.weekday_hours = {"1": [{"start": "09:00", "end": "17:00"}]}
    calendar.holidays = []
    calendar.save(update_fields=["timezone", "weekday_hours", "holidays"])
    instance.due_at = resumed_at + timedelta(hours=2)
    instance.save(
        update_fields=[
            "due_at",
            "remaining_business_microseconds",
            "remaining_business_seconds",
        ]
    )

    old_pause = SlaPauseHistory.objects.create(
        instance=instance,
        state=SlaInstance.State.PAUSED_REQUESTER,
        reason="old_pause",
    )
    resumed = SlaPauseHistory.objects.create(
        instance=instance,
        state=SlaInstance.State.ACTIVE,
        reason="resumed",
    )
    current_pause = SlaPauseHistory.objects.create(
        instance=instance,
        state=SlaInstance.State.PAUSED_INTERNAL,
        reason="current_pause",
    )
    SlaPauseHistory.objects.filter(pk__in=[old_pause.pk, resumed.pk]).update(at=resumed_at)
    SlaPauseHistory.objects.filter(pk=current_pause.pk).update(at=current_pause_at)

    with freeze_time(legacy_retry_at):
        resume_sla(instance=instance, reason="legacy_retry")

    instance.refresh_from_db()
    assert instance.due_at == legacy_retry_at + timedelta(hours=1, minutes=45)


def test_resume_recovers_suspicious_legacy_zero_after_current_pause(basic_world):
    """A historical zero cannot be trusted when the persisted deadline is later."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket, state=SlaInstance.State.PAUSED_REQUESTER)
    at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    instance.due_at = at + timedelta(hours=1)
    instance.remaining_business_microseconds = None
    instance.remaining_business_seconds = 0
    instance.save(
        update_fields=[
            "due_at",
            "remaining_business_microseconds",
            "remaining_business_seconds",
        ]
    )
    SlaPauseHistory.objects.create(
        instance=instance,
        state=SlaInstance.State.ACTIVE,
        reason="same_instant_resume",
    )
    SlaPauseHistory.objects.create(
        instance=instance,
        state=SlaInstance.State.PAUSED_REQUESTER,
        reason="same_instant_pause",
    )
    SlaPauseHistory.objects.filter(instance=instance).update(at=at)

    with freeze_time(at):
        resume_sla(instance=instance, reason="legacy_retry")

    instance.refresh_from_db()
    assert instance.due_at == at + timedelta(hours=1)


def test_restart_resolution_clears_frozen_pause_entitlement(basic_world):
    """A reopened resolution SLA must not carry a prior pause's frozen clock."""
    ticket = _ticket(basic_world, status_code="reopened")
    reopened_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    ticket.reopened_at = reopened_at
    ticket.save(update_fields=["reopened_at"])
    instance = _instance(ticket, state=SlaInstance.State.PAUSED_REQUESTER)
    instance.remaining_business_seconds = 120
    instance.remaining_business_microseconds = 120000001
    instance.save(
        update_fields=[
            "remaining_business_seconds",
            "remaining_business_microseconds",
        ]
    )

    restarted = restart_resolution_sla(ticket=ticket, at=reopened_at)

    assert restarted is not None
    restarted.refresh_from_db()
    assert restarted.remaining_business_seconds is None
    assert restarted.remaining_business_microseconds is None


def test_evaluator_rolls_back_escalation_when_custody_recording_fails(basic_world):
    """A custody failure must roll audit, outbox, and notification state back."""
    ticket = _ticket(basic_world)
    instance = _instance(ticket)
    started_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)
    threshold_time = _set_resolution_escalation_threshold(
        instance,
        started_at=started_at,
    )

    with freeze_time(threshold_time), patch(
        "apps.tickets.events.record_custody_events",
        side_effect=RuntimeError("custody unavailable"),
    ):
        with pytest.raises(RuntimeError, match="custody unavailable"):
            evaluate_open_slas()

    instance.refresh_from_db()
    assert instance.escalation_notified_at is None
    assert ticket.custody_events.filter(event_type="escalated").count() == 0
    assert AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.escalated"
    ).count() == 0
    assert OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type="ticket.escalated"
    ).count() == 0


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


def test_waiting_to_different_waiting_state_remaps_pause_and_records_history(
    basic_world,
):
    ticket = _ticket(basic_world, status_code="waiting_requester")
    instance = _instance(ticket, state="paused_requester")

    sync_slas_for_transition(
        ticket=ticket,
        from_code="waiting_requester",
        to_code="waiting_internal",
        actor_subject="agent-2",
    )

    instance.refresh_from_db()
    history = SlaPauseHistory.objects.get(instance=instance)
    assert instance.state == "paused_internal"
    assert history.state == "paused_internal"
    assert history.actor_subject == "agent-2"


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
    breached_completion_at = at + timedelta(minutes=1)
    complete_sla(
        ticket=ticket,
        kind="resolution",
        at=breached_completion_at,
    )
    active.refresh_from_db()
    assert active.state == "breached"
    assert active.completed_at == breached_completion_at


def test_reopen_restarts_existing_resolution_clock_from_reopened_at(basic_world):
    ticket = _ticket(basic_world, status_code="reopened")
    reopened_at = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)
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
