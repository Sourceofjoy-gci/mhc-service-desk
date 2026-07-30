"""SLA service — business calendar math, instance creation, evaluator.

Why: SLA deadlines must survive queue restarts (PRD §25.3). Storing them
in PostgreSQL and evaluating periodically keeps the system honest.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.tickets.custody import CustodyActor, CustodyEventInput, status_snapshot
from apps.tickets.events import record_ticket_event
from apps.tickets.models import Ticket

from .models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Business calendar math
# -----------------------------------------------------------------------------

def _normalized_weekday_intervals(
    calendar: BusinessCalendar,
    day_key: str,
) -> list[tuple[time, time]]:
    """Return a defensive union of valid persisted intervals for one day."""
    if not isinstance(calendar.weekday_hours, dict):
        return []
    raw_intervals = calendar.weekday_hours.get(day_key, [])
    if not isinstance(raw_intervals, list):
        return []
    intervals: list[tuple[time, time]] = []
    for raw_interval in raw_intervals:
        try:
            start = time.fromisoformat(raw_interval["start"])
            end = time.fromisoformat(raw_interval["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        intervals.append((start, end))
    intervals.sort()

    merged: list[tuple[time, time]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged

def _timedelta_microseconds(value: timedelta) -> int:
    return (value.days * 24 * 60 * 60 + value.seconds) * 1_000_000 + value.microseconds


def _add_business_microseconds(
    start: datetime,
    microseconds: int,
    calendar: BusinessCalendar,
) -> datetime:
    """Add exact business microseconds to ``start`` honouring calendar slots."""
    if microseconds <= 0:
        return start
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("SLA business-time calculations require an aware start")

    output_timezone = start.tzinfo
    calendar_timezone = ZoneInfo(calendar.timezone)
    remaining = microseconds
    cursor = start.astimezone(calendar_timezone)
    holiday_set = set(calendar.holidays)

    # Cap iterations to avoid infinite loops; each loop advances at least a day.
    safety = 365 * 24 * 60 * 60
    while remaining > 0 and safety > 0:
        safety -= 1
        date = cursor.date()
        iso_weekday = date.isoweekday()
        day_key = str(iso_weekday)
        intervals = _normalized_weekday_intervals(calendar, day_key)
        if date.isoformat() in holiday_set or not intervals:
            cursor = datetime.combine(
                date + timedelta(days=1),
                time.min,
                tzinfo=calendar_timezone,
            )
            continue

        for t_start, t_end in intervals:
            slot_start = datetime.combine(date, t_start, tzinfo=calendar_timezone)
            slot_end = datetime.combine(date, t_end, tzinfo=calendar_timezone)
            cursor_utc = cursor.astimezone(UTC)
            slot_start_utc = slot_start.astimezone(UTC)
            slot_end_utc = slot_end.astimezone(UTC)
            if cursor_utc >= slot_end_utc:
                continue
            if cursor_utc < slot_start_utc:
                cursor = slot_start
                cursor_utc = slot_start_utc
            available = _timedelta_microseconds(slot_end_utc - cursor_utc)
            if available <= 0:
                continue
            consume = min(available, remaining)
            cursor = (cursor_utc + timedelta(microseconds=consume)).astimezone(
                calendar_timezone
            )
            remaining -= consume
            if remaining <= 0:
                return cursor.astimezone(output_timezone)
        # roll into the next day
        cursor = datetime.combine(
            date + timedelta(days=1),
            time.min,
            tzinfo=calendar_timezone,
        )
    return cursor.astimezone(output_timezone)


def add_business_seconds(
    start: datetime,
    seconds: int,
    calendar: BusinessCalendar,
) -> datetime:
    """Add N business seconds to ``start`` honouring weekday hours and holidays."""
    return _add_business_microseconds(start, seconds * 1_000_000, calendar)


def _business_microseconds_between(
    start: datetime,
    end: datetime,
    calendar: BusinessCalendar,
) -> int:
    """Return exact business microseconds in ``[start, end)`` for one calendar."""
    if (
        start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
    ):
        raise ValueError("SLA business-time calculations require aware endpoints")

    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    if end_utc <= start_utc:
        return 0

    total_microseconds = 0
    calendar_timezone = ZoneInfo(calendar.timezone)
    holiday_set = set(calendar.holidays)
    current_date = start.astimezone(calendar_timezone).date()
    end_date = end.astimezone(calendar_timezone).date()
    while current_date <= end_date:
        if current_date.isoformat() not in holiday_set:
            for interval_start, interval_end in _normalized_weekday_intervals(
                calendar, str(current_date.isoweekday())
            ):
                slot_start = datetime.combine(
                    current_date,
                    interval_start,
                    tzinfo=calendar_timezone,
                ).astimezone(UTC)
                slot_end = datetime.combine(
                    current_date,
                    interval_end,
                    tzinfo=calendar_timezone,
                ).astimezone(UTC)
                overlap_start = max(start_utc, slot_start)
                overlap_end = min(end_utc, slot_end)
                if overlap_end > overlap_start:
                    overlap = overlap_end - overlap_start
                    total_microseconds += _timedelta_microseconds(overlap)
        current_date += timedelta(days=1)
    return total_microseconds


def business_seconds_between(
    start: datetime,
    end: datetime,
    calendar: BusinessCalendar,
) -> int:
    """Return whole business seconds in ``[start, end)`` for one calendar."""
    return _business_microseconds_between(start, end, calendar) // 1_000_000


# -----------------------------------------------------------------------------
# Instance creation
# -----------------------------------------------------------------------------

def instantiate_slas(*, ticket: Ticket, policy: SlaPolicy) -> list[SlaInstance]:
    """Create one SlaInstance per target for a freshly created ticket."""
    calendar = policy.calendar
    targets = []
    if policy.acknowledgement_minutes:
        targets.append(("acknowledgement", policy.acknowledgement_minutes))
    if policy.first_response_minutes:
        targets.append(("first_response", policy.first_response_minutes))
    if policy.resolution_minutes:
        targets.append(("resolution", policy.resolution_minutes))

    instances: list[SlaInstance] = []
    start = ticket.created_at
    for kind, minutes in targets:
        due = add_business_seconds(start, minutes * 60, calendar)
        instances.append(
            SlaInstance.objects.create(
                ticket=ticket, policy=policy, kind=kind, due_at=due
            )
        )
    return instances


# -----------------------------------------------------------------------------
# Pause / resume
# -----------------------------------------------------------------------------

PAUSABLE_STATES_FOR_REQUESTER = {"paused_requester"}
PAUSABLE_STATES_FOR_INTERNAL = {"paused_internal", "paused_it"}

WAITING_SLA_STATES = {
    "operational": {
        "waiting_requester": SlaInstance.State.PAUSED_REQUESTER,
        "waiting_internal": SlaInstance.State.PAUSED_INTERNAL,
        "waiting_it": SlaInstance.State.PAUSED_IT,
    },
    "it": {
        "waiting_user": SlaInstance.State.PAUSED_REQUESTER,
        "waiting_vendor": SlaInstance.State.PAUSED_INTERNAL,
        "waiting_change": SlaInstance.State.PAUSED_INTERNAL,
    },
}

PAUSED_SLA_STATES = {
    SlaInstance.State.PAUSED_REQUESTER,
    SlaInstance.State.PAUSED_INTERNAL,
    SlaInstance.State.PAUSED_IT,
}


def _first_current_pause_at(instance: SlaInstance) -> datetime | None:
    histories = instance.pause_history.all()
    last_resumed_at = (
        histories.filter(state=SlaInstance.State.ACTIVE)
        .order_by("-at")
        .values_list("at", flat=True)
        .first()
    )
    current_pauses = histories.filter(state__in=PAUSED_SLA_STATES)
    if last_resumed_at is not None:
        strictly_later_pause = (
            current_pauses.filter(at__gt=last_resumed_at)
            .order_by("at")
            .values_list("at", flat=True)
            .first()
        )
        if strictly_later_pause is not None:
            return strictly_later_pause
        current_pauses = current_pauses.filter(at=last_resumed_at)
    return current_pauses.order_by("at").values_list("at", flat=True).first()


def _recover_legacy_remaining_business_seconds(instance: SlaInstance) -> int:
    """Recover persisted wall time without assuming a calendar's history."""
    paused_at = _first_current_pause_at(instance)
    if paused_at is None:
        return 0
    return max(
        0,
        int(
            (
                instance.due_at.astimezone(UTC) - paused_at.astimezone(UTC)
            ).total_seconds()
        ),
    )


def _legacy_remaining_business_seconds(instance: SlaInstance) -> int:
    remaining = instance.remaining_business_seconds
    if remaining is None:
        return _recover_legacy_remaining_business_seconds(instance)
    if remaining != 0 or instance.state not in PAUSED_SLA_STATES:
        return remaining
    paused_at = _first_current_pause_at(instance)
    if paused_at is None or instance.due_at.astimezone(UTC) <= paused_at.astimezone(UTC):
        return remaining
    return _recover_legacy_remaining_business_seconds(instance)


@transaction.atomic
def pause_sla(
    *,
    instance: SlaInstance,
    reason: str,
    actor_subject: str = "",
) -> SlaInstance:
    instance = (
        SlaInstance.objects.select_for_update()
        .select_related("policy__calendar")
        .get(pk=instance.pk)
    )
    if instance.state == SlaInstance.State.ACTIVE:
        remaining_microseconds = _business_microseconds_between(
            timezone.now(),
            instance.due_at,
            instance.policy.calendar,
        )
        instance.remaining_business_microseconds = remaining_microseconds
        instance.remaining_business_seconds = remaining_microseconds // 1_000_000
    elif instance.remaining_business_seconds is None:
        instance.remaining_business_seconds = (
            _recover_legacy_remaining_business_seconds(instance)
        )
    instance.state = reason
    instance.save(
        update_fields=[
            "state",
            "remaining_business_seconds",
            "remaining_business_microseconds",
            "updated_at",
        ]
    )
    SlaPauseHistory.objects.create(
        instance=instance,
        state=reason,
        reason=reason,
        actor_subject=actor_subject,
    )
    return instance


@transaction.atomic
def resume_sla(*, instance: SlaInstance, reason: str, actor_subject: str = "") -> SlaInstance:
    instance = (
        SlaInstance.objects.select_for_update()
        .select_related("policy__calendar")
        .get(pk=instance.pk)
    )
    if instance.state == "active":
        return instance
    remaining_microseconds = instance.remaining_business_microseconds
    if remaining_microseconds is None:
        remaining_business_seconds = _legacy_remaining_business_seconds(instance)
        remaining_microseconds = remaining_business_seconds * 1_000_000
    if remaining_microseconds is not None:
        instance.due_at = _add_business_microseconds(
            timezone.now(),
            remaining_microseconds,
            instance.policy.calendar,
        )
    instance.state = "active"
    instance.remaining_business_seconds = (
        0 if remaining_microseconds == 0 else None
    )
    instance.remaining_business_microseconds = (
        0 if remaining_microseconds == 0 else None
    )
    instance.save(
        update_fields=[
            "state",
            "due_at",
            "remaining_business_seconds",
            "remaining_business_microseconds",
            "updated_at",
        ]
    )
    SlaPauseHistory.objects.create(
        instance=instance,
        state="active",
        reason=reason,
        actor_subject=actor_subject,
    )
    return instance


@transaction.atomic
def complete_sla(*, ticket: Ticket, kind: str, at: datetime) -> SlaInstance | None:
    """Complete one active SLA, preserving an already-recorded breach."""
    instance = (
        SlaInstance.objects.select_for_update()
        .filter(ticket=ticket, kind=kind)
        .order_by("created_at", "id")
        .first()
    )
    if instance is None:
        return instance
    if instance.state == SlaInstance.State.BREACHED:
        if instance.completed_at is None:
            instance.completed_at = at
            instance.save(update_fields=["completed_at", "updated_at"])
        return instance
    if instance.state == SlaInstance.State.MET:
        return instance
    overdue = (
        instance.state == SlaInstance.State.ACTIVE
        and (
            at >= instance.due_at
            or instance.remaining_business_seconds == 0
        )
    ) or (
        instance.state in PAUSED_SLA_STATES
        and instance.remaining_business_seconds in {None, 0}
    )
    instance.state = SlaInstance.State.BREACHED if overdue else SlaInstance.State.MET
    instance.completed_at = at
    update_fields = ["state", "completed_at", "updated_at"]
    if overdue:
        instance.breached_at = min(instance.due_at, at)
        update_fields.append("breached_at")
    instance.save(update_fields=update_fields)
    return instance


@transaction.atomic
def restart_resolution_sla(*, ticket: Ticket, at: datetime) -> SlaInstance | None:
    """Restart the existing resolution measurement after a reopen."""
    instance = (
        SlaInstance.objects.select_for_update()
        .select_related("policy__calendar")
        .filter(ticket=ticket, kind="resolution")
        .order_by("created_at", "id")
        .first()
    )
    creating = instance is None
    if creating:
        policy = SlaPolicy.objects.select_related("calendar").filter(
            domain=ticket.domain,
            priority=ticket.priority,
            is_active=True,
        ).first()
        if policy is None:
            return None
        instance = SlaInstance(ticket=ticket, policy=policy, kind="resolution")

    instance.started_at = at
    instance.due_at = add_business_seconds(
        at,
        instance.policy.resolution_minutes * 60,
        instance.policy.calendar,
    )
    instance.state = SlaInstance.State.ACTIVE
    instance.consumed_business_seconds = 0
    instance.remaining_business_seconds = None
    instance.remaining_business_microseconds = None
    instance.completed_at = None
    instance.breached_at = None
    instance.breach_reason = ""
    instance.last_evaluated_at = None
    instance.warn_notified_at = None
    instance.escalation_notified_at = None
    if creating:
        instance.save()
    else:
        instance.save(
            update_fields=[
                "started_at",
                "due_at",
                "state",
                "consumed_business_seconds",
                "remaining_business_seconds",
                "remaining_business_microseconds",
                "completed_at",
                "breached_at",
                "breach_reason",
                "last_evaluated_at",
                "warn_notified_at",
                "escalation_notified_at",
                "updated_at",
            ]
        )
    return instance


@transaction.atomic
def sync_slas_for_transition(
    *,
    ticket: Ticket,
    from_code: str,
    to_code: str,
    actor_subject: str,
) -> None:
    """Synchronize all live clocks with one accepted workflow transition."""
    target_pause_state = WAITING_SLA_STATES.get(ticket.domain, {}).get(to_code)
    prior_pause_state = WAITING_SLA_STATES.get(ticket.domain, {}).get(from_code)

    if target_pause_state is not None:
        for instance in SlaInstance.objects.select_for_update().filter(
            ticket=ticket,
            state=SlaInstance.State.ACTIVE,
        ):
            pause_sla(
                instance=instance,
                reason=target_pause_state,
                actor_subject=actor_subject,
            )
        for instance in SlaInstance.objects.select_for_update().filter(
            ticket=ticket,
            state__in=(
                SlaInstance.State.PAUSED_REQUESTER,
                SlaInstance.State.PAUSED_INTERNAL,
                SlaInstance.State.PAUSED_IT,
            ),
        ).exclude(state=target_pause_state):
            pause_sla(
                instance=instance,
                reason=target_pause_state,
                actor_subject=actor_subject,
            )
    elif prior_pause_state is not None:
        for instance in SlaInstance.objects.select_for_update().filter(
            ticket=ticket,
            state__in=(
                SlaInstance.State.PAUSED_REQUESTER,
                SlaInstance.State.PAUSED_INTERNAL,
                SlaInstance.State.PAUSED_IT,
            ),
        ):
            resume_sla(
                instance=instance,
                reason=f"left_{from_code}",
                actor_subject=actor_subject,
            )

    if to_code == "resolved" and ticket.resolved_at is not None:
        complete_sla(
            ticket=ticket,
            kind="resolution",
            at=ticket.resolved_at,
        )
    elif to_code == "reopened" and ticket.reopened_at is not None:
        restart_resolution_sla(ticket=ticket, at=ticket.reopened_at)


# -----------------------------------------------------------------------------
# Periodic evaluator
# -----------------------------------------------------------------------------


def _target_seconds(instance: SlaInstance) -> int:
    minutes = {
        "acknowledgement": instance.policy.acknowledgement_minutes,
        "first_response": instance.policy.first_response_minutes,
        "update": instance.policy.update_interval_minutes,
        "resolution": instance.policy.resolution_minutes,
    }.get(instance.kind, 0)
    return minutes * 60


def _crossed_escalation_threshold(instance: SlaInstance, now: datetime) -> bool:
    target = _target_seconds(instance)
    if target <= 0 or instance.state != SlaInstance.State.ACTIVE:
        return False
    target_microseconds = target * 1_000_000
    remaining = _business_microseconds_between(
        now,
        instance.due_at,
        instance.policy.calendar,
    )
    consumed = max(0, target_microseconds - remaining)
    return consumed * 100 >= target_microseconds * instance.policy.escalation_percent


def _record_escalation(*, ticket: Ticket, instance: SlaInstance, now: datetime) -> None:
    """Record the immutable ticket history for one newly crossed SLA threshold."""
    reason = (
        f"{instance.kind.replace('_', ' ')} SLA crossed the "
        f"{instance.policy.escalation_percent}% escalation threshold"
    )
    before = {
        "sla": {
            "instance_id": str(instance.id),
            "kind": instance.kind,
            "escalation_notified_at": None,
        }
    }
    after = {
        "sla": {
            "instance_id": str(instance.id),
            "kind": instance.kind,
            "escalation_notified_at": now,
        }
    }
    ticket_status = status_snapshot(ticket.status)
    record_ticket_event(
        ticket=ticket,
        actor_subject="sla:evaluator",
        action="ticket.escalated",
        before=before,
        after=after,
        metadata={
            "sla_instance_id": str(instance.id),
            "sla_kind": instance.kind,
            "escalation_percent": instance.policy.escalation_percent,
        },
        custody_actor=CustodyActor.system("sla:evaluator", "SLA evaluator"),
        custody_events=(
            CustodyEventInput(
                event_type="escalated",
                source_process="sla.escalation",
                source_record_type="sla_instance",
                source_record_id=str(instance.id),
                previous_status=ticket_status,
                new_status=ticket_status,
                reason=reason,
                occurred_at=now,
            ),
        ),
    )


@transaction.atomic
def evaluate_open_slas() -> int:
    """Walk all open SLA instances, mark breaches, return count evaluated."""
    now = timezone.now()
    open_states = ["active", "paused_requester", "paused_internal", "paused_it"]
    candidates = (
        SlaInstance.objects.filter(state__in=open_states)
        .order_by("ticket_id", "id")
        .values_list("id", "ticket_id")
    )
    evaluated = 0
    breached = 0
    for instance_id, ticket_id in candidates.iterator(chunk_size=500):
        # Every workflow transition takes this aggregate lock before touching its
        # SLA rows.  Preserve that ordering here before re-reading current SLA
        # state; the candidate list is intentionally not decision state.
        try:
            ticket = Ticket.objects.select_for_update().select_related("status").get(pk=ticket_id)
        except Ticket.DoesNotExist:
            continue
        inst = (
            SlaInstance.objects.select_for_update(skip_locked=True)
            .select_related("policy__calendar")
            .filter(pk=instance_id, ticket_id=ticket.id, state__in=open_states)
            .first()
        )
        if inst is None:
            continue
        evaluated += 1
        if inst.state != "active":
            continue
        update_fields = ["last_evaluated_at", "updated_at"]
        if inst.escalation_notified_at is None and _crossed_escalation_threshold(inst, now):
            _record_escalation(ticket=ticket, instance=inst, now=now)
            inst.escalation_notified_at = now
            update_fields.append("escalation_notified_at")
        if inst.due_at <= now:
            inst.state = "breached"
            inst.breached_at = now
            update_fields.extend(["state", "breached_at"])
            breached += 1
        inst.last_evaluated_at = now
        inst.save(update_fields=update_fields)
    logger.info("sla_evaluator_run", extra={"evaluated": evaluated, "breached": breached})
    return evaluated
