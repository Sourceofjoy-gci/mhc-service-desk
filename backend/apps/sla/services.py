"""SLA service — business calendar math, instance creation, evaluator.

Why: SLA deadlines must survive queue restarts (PRD §25.3). Storing them
in PostgreSQL and evaluating periodically keeps the system honest.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from apps.tickets.models import Ticket

from .models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Business calendar math
# -----------------------------------------------------------------------------

def add_business_seconds(
    start: datetime,
    seconds: int,
    calendar: BusinessCalendar,
) -> datetime:
    """Add N business seconds to ``start`` honouring weekday hours and holidays.

    Simple, correct, and easy to test. The PRD calls for a calendar that
    supports multi-interval business days; this implementation handles that
    via ``weekday_hours``.
    """
    if seconds <= 0:
        return start
    remaining = seconds
    cursor = start
    holiday_set = set(calendar.holidays)

    # Cap iterations to avoid infinite loops; each loop consumes at least
    # one business second across at most ~365 days.
    safety = 365 * 24 * 60 * 60
    while remaining > 0 and safety > 0:
        safety -= 1
        date = cursor.date()
        iso_weekday = date.isoweekday()
        day_key = str(iso_weekday)
        intervals = calendar.weekday_hours.get(day_key, [])
        if date.isoformat() in holiday_set or not intervals:
            cursor = datetime.combine(date + timedelta(days=1), time.min, tzinfo=cursor.tzinfo)
            continue

        for interval in intervals:
            t_start = time.fromisoformat(interval["start"])
            t_end = time.fromisoformat(interval["end"])
            slot_start = datetime.combine(date, t_start, tzinfo=cursor.tzinfo)
            slot_end = datetime.combine(date, t_end, tzinfo=cursor.tzinfo)
            if cursor >= slot_end:
                continue
            if cursor < slot_start:
                cursor = slot_start
            available = int((slot_end - cursor).total_seconds())
            if available <= 0:
                continue
            consume = min(available, remaining)
            cursor = cursor + timedelta(seconds=consume)
            remaining -= consume
            if remaining <= 0:
                return cursor
        # roll into the next day
        cursor = datetime.combine(date + timedelta(days=1), time.min, tzinfo=cursor.tzinfo)
    return cursor


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


@transaction.atomic
def pause_sla(
    *,
    instance: SlaInstance,
    reason: str,
    actor_subject: str = "",
) -> SlaInstance:
    instance.state = reason
    instance.save(update_fields=["state", "updated_at"])
    SlaPauseHistory.objects.create(
        instance=instance,
        state=reason,
        reason=reason,
        actor_subject=actor_subject,
    )
    return instance


@transaction.atomic
def resume_sla(*, instance: SlaInstance, reason: str, actor_subject: str = "") -> SlaInstance:
    if instance.state == "active":
        return instance
    instance.state = "active"
    instance.save(update_fields=["state", "updated_at"])
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
    if instance is None or instance.state == SlaInstance.State.BREACHED:
        return instance
    if instance.state == SlaInstance.State.MET:
        return instance
    instance.state = SlaInstance.State.MET
    instance.completed_at = at
    instance.save(update_fields=["state", "completed_at", "updated_at"])
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
    if instance is None:
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
    instance.completed_at = None
    instance.breached_at = None
    instance.breach_reason = ""
    instance.last_evaluated_at = None
    instance.warn_notified_at = None
    instance.escalation_notified_at = None
    instance.save()
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

def evaluate_open_slas() -> int:
    """Walk all open SLA instances, mark breaches, return count evaluated."""
    now = timezone.now()
    qs = SlaInstance.objects.filter(
        state__in=["active", "paused_requester", "paused_internal", "paused_it"]
    )
    evaluated = 0
    breached = 0
    for inst in qs.iterator(chunk_size=500):
        evaluated += 1
        if inst.state != "active":
            continue
        if inst.due_at <= now and inst.state == "active":
            inst.state = "breached"
            inst.breached_at = now
            inst.save(update_fields=["state", "breached_at", "updated_at"])
            breached += 1
        inst.last_evaluated_at = now
        inst.save(update_fields=["last_evaluated_at", "updated_at"])
    logger.info("sla_evaluator_run", extra={"evaluated": evaluated, "breached": breached})
    return evaluated
