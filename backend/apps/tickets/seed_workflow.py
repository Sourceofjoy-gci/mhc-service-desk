"""Seed default operational and IT workflows.

Called by ``scripts/seed_dev.py``. Idempotent: re-running is safe.
"""
from __future__ import annotations

from apps.workflow.models import Status, Transition

OPERATIONAL_STATUSES = [
    ("new", "New", True, False, 10, "Received"),
    ("triage", "Triage", False, False, 20, "Being reviewed"),
    ("assigned", "Assigned", False, False, 30, "Assigned"),
    ("in_progress", "In Progress", False, False, 40, "Being worked on"),
    (
        "waiting_requester",
        "Waiting for Requester",
        False,
        False,
        50,
        "Waiting for your information",
    ),
    ("waiting_internal", "Waiting for Internal Unit", False, False, 60, "Referred internally"),
    ("waiting_it", "Waiting for IT", False, False, 70, "Referred internally"),
    ("quality_review", "Quality Review", False, False, 80, "Being reviewed"),
    ("resolved", "Resolved", False, False, 90, "Response provided"),
    ("closed", "Closed", False, True, 100, "Closed"),
    ("cancelled", "Cancelled", False, True, 110, ""),
    ("rejected", "Rejected", False, True, 120, ""),
    ("duplicate", "Duplicate", False, True, 130, ""),
    ("spam", "Spam", False, True, 140, ""),
    ("reopened", "Reopened", False, False, 45, "Being worked on"),
]

OPERATIONAL_TRANSITIONS = [
    ("new", "triage", "Begin triage"),
    ("triage", "assigned", "Assign"),
    ("triage", "in_progress", "Start work"),
    ("triage", "waiting_internal", "Refer internally"),
    ("triage", "waiting_it", "Refer to IT"),
    ("triage", "duplicate", "Mark duplicate"),
    ("triage", "spam", "Mark spam"),
    ("triage", "cancelled", "Cancel"),
    ("triage", "rejected", "Reject"),
    ("assigned", "in_progress", "Start work"),
    ("assigned", "waiting_requester", "Wait on requester"),
    ("in_progress", "waiting_requester", "Wait on requester"),
    ("in_progress", "waiting_internal", "Wait on internal"),
    ("in_progress", "waiting_it", "Wait on IT"),
    ("in_progress", "quality_review", "Send to quality review"),
    ("waiting_requester", "in_progress", "Requester replied"),
    ("waiting_internal", "in_progress", "Internal reply received"),
    ("waiting_it", "in_progress", "IT reply received"),
    ("quality_review", "in_progress", "Returned from QA"),
    ("quality_review", "resolved", "Close after QA", True),
    ("in_progress", "resolved", "Resolve", True),
    ("resolved", "reopened", "Reopen"),
    ("reopened", "in_progress", "Resume work"),
    ("resolved", "closed", "Close"),
    ("cancelled", "closed", "Close"),
    ("rejected", "closed", "Close"),
    ("duplicate", "closed", "Close"),
    ("spam", "closed", "Close"),
]

IT_STATUSES = [
    ("new", "New", True, False, 10, "Received"),
    ("triage", "Triage", False, False, 20, "Being reviewed"),
    ("assigned", "Assigned", False, False, 30, "Assigned"),
    ("diagnosing", "Diagnosing", False, False, 40, "Being worked on"),
    ("in_progress", "In Progress", False, False, 50, "Being worked on"),
    ("waiting_user", "Waiting for User", False, False, 60, "Waiting for your information"),
    ("waiting_vendor", "Waiting for Vendor", False, False, 70, "Waiting externally"),
    ("waiting_change", "Waiting for Change", False, False, 80, "Scheduled"),
    ("validation", "Validation", False, False, 85, "Being reviewed"),
    ("resolved", "Resolved", False, False, 90, "Completed"),
    ("closed", "Closed", False, True, 100, "Closed"),
    ("cancelled", "Cancelled", False, True, 110, ""),
    ("reopened", "Reopened", False, False, 55, "Being worked on"),
]

IT_TRANSITIONS = [
    ("new", "triage", "Begin triage"),
    ("triage", "assigned", "Assign"),
    ("triage", "in_progress", "Start work"),
    ("triage", "diagnosing", "Begin diagnosis"),
    ("triage", "cancelled", "Cancel"),
    ("assigned", "diagnosing", "Begin diagnosis"),
    ("assigned", "in_progress", "Start work"),
    ("diagnosing", "in_progress", "Move to work"),
    ("in_progress", "waiting_user", "Wait on user"),
    ("in_progress", "waiting_vendor", "Wait on vendor"),
    ("in_progress", "waiting_change", "Schedule change"),
    ("waiting_user", "in_progress", "User replied"),
    ("waiting_vendor", "in_progress", "Vendor replied"),
    ("waiting_change", "validation", "Change complete"),
    ("in_progress", "validation", "Send to validation"),
    ("validation", "resolved", "Close", True),
    ("validation", "in_progress", "Returned from validation"),
    ("resolved", "reopened", "Reopen"),
    ("reopened", "in_progress", "Resume work"),
    ("resolved", "closed", "Close"),
]


def seed_workflow() -> None:
    """Idempotent seed of statuses and transitions for both domains."""
    for domain, statuses, transitions in [
        ("operational", OPERATIONAL_STATUSES, OPERATIONAL_TRANSITIONS),
        ("it", IT_STATUSES, IT_TRANSITIONS),
    ]:
        status_map: dict[str, Status] = {}
        for code, name, is_initial, is_terminal, order, public_label in statuses:
            obj, _ = Status.objects.update_or_create(
                code=code, domain=domain,
                defaults={
                    "name": name, "is_initial": is_initial,
                    "is_terminal": is_terminal, "order": order,
                    "public_label": public_label,
                },
            )
            status_map[code] = obj
        for t in transitions:
            if len(t) == 4:
                frm, to, name, sets_resolution = t
            else:
                frm, to, name = t
                sets_resolution = False
            Transition.objects.update_or_create(
                domain=domain,
                from_status=status_map[frm],
                to_status=status_map[to],
                defaults={"name": name, "sets_resolution": sets_resolution, "is_active": True},
            )
