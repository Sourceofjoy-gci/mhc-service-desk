"""Requester-safe ticket progress projection for authenticated staff."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import TypedDict

from apps.workflow.models import Status

from .models import Ticket


class TrackingStatus(StrEnum):
    SUBMITTED = "Submitted"
    ACKNOWLEDGED = "Acknowledged"
    ASSIGNED = "Assigned"
    IN_PROGRESS = "In Progress"
    AWAITING_INFORMATION = "Awaiting Information"
    ESCALATED = "Escalated"
    RESOLVED = "Resolved"
    CLOSED = "Closed"
    REOPENED = "Reopened"


class TrackingProgressItem(TypedDict):
    status: TrackingStatus
    occurred_at: datetime


class TrackingProjection(TypedDict):
    progress: list[TrackingProgressItem]
    status_updated_at: datetime


TRACKING_BY_CODE = {
    "new": TrackingStatus.SUBMITTED,
    "triage": TrackingStatus.ACKNOWLEDGED,
    "assigned": TrackingStatus.ASSIGNED,
    "in_progress": TrackingStatus.IN_PROGRESS,
    "diagnosing": TrackingStatus.IN_PROGRESS,
    "quality_review": TrackingStatus.IN_PROGRESS,
    "validation": TrackingStatus.IN_PROGRESS,
    "escalated": TrackingStatus.ESCALATED,
    "resolved": TrackingStatus.RESOLVED,
    "reopened": TrackingStatus.REOPENED,
    "closed": TrackingStatus.CLOSED,
    "cancelled": TrackingStatus.CLOSED,
    "rejected": TrackingStatus.CLOSED,
    "duplicate": TrackingStatus.CLOSED,
    "spam": TrackingStatus.CLOSED,
}


def tracking_status_for(
    status: Status | Mapping[str, object],
) -> TrackingStatus:
    if isinstance(status, Status):
        code = status.code
        terminal = status.is_terminal
    else:
        code = str(status.get("code", ""))
        terminal = bool(status.get("is_terminal", False))
    if code.startswith("waiting_"):
        return TrackingStatus.AWAITING_INFORMATION
    return TRACKING_BY_CODE.get(
        code,
        TrackingStatus.CLOSED if terminal else TrackingStatus.IN_PROGRESS,
    )


def build_tracking_projection(ticket: Ticket) -> TrackingProjection:
    """Return public milestones plus the latest underlying status-change time."""

    status_terminal = dict(
        Status.objects.filter(domain=ticket.domain).values_list(
            "code",
            "is_terminal",
        )
    )
    represented_transition_ids: set[str] = set()
    milestones: list[tuple[datetime, str, TrackingStatus]] = []

    for event in ticket.custody_events.all():
        if event.source_record_type == "workflow_transition" and event.source_record_id:
            represented_transition_ids.add(event.source_record_id)
        if not event.new_status or not event.new_status.get("code"):
            continue
        code = str(event.new_status["code"])
        milestones.append(
            (
                event.occurred_at,
                f"custody:{event.sequence:020d}:{event.pk}",
                tracking_status_for(
                    {
                        "code": code,
                        "is_terminal": status_terminal.get(code, False),
                    }
                ),
            )
        )

    for history in ticket.transition_history.select_related("to_status"):
        if str(history.pk) in represented_transition_ids:
            continue
        milestones.append(
            (
                history.occurred_at,
                f"transition:{history.pk}",
                tracking_status_for(history.to_status),
            )
        )

    if not milestones:
        milestones.append(
            (
                ticket.created_at,
                f"ticket:{ticket.pk}",
                tracking_status_for(ticket.status),
            )
        )

    ordered_milestones = sorted(milestones)
    progress: list[TrackingProgressItem] = []
    for occurred_at, _stable_id, status in ordered_milestones:
        if progress and progress[-1]["status"] == status:
            continue
        progress.append({"status": status, "occurred_at": occurred_at})
    return {
        "progress": progress,
        "status_updated_at": ordered_milestones[-1][0],
    }


def build_tracking_progress(ticket: Ticket) -> list[TrackingProgressItem]:
    """Return only public status labels and timestamps, in lifecycle order."""

    return build_tracking_projection(ticket)["progress"]
