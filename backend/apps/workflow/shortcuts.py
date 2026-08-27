"""Helper used by tests to seed the workflow without running the full CLI seed.

Kept separate so the test suite doesn't need Django settings configured for
``apps.tickets.seed_workflow``.
"""

from __future__ import annotations

from .models import Status, Transition


def seed_workflow_for_tests() -> None:
    statuses = {
        ("operational", "new"): ("New", True, False, 10, "Received"),
        ("operational", "triage"): ("Triage", False, False, 20, "Being reviewed"),
        ("operational", "assigned"): ("Assigned", False, False, 30, "Assigned"),
        ("operational", "in_progress"): ("In Progress", False, False, 40, "Being worked on"),
        ("operational", "escalated"): (
            "Escalated",
            False,
            False,
            85,
            "Escalated for attention",
        ),
        ("operational", "resolved"): ("Resolved", False, False, 90, "Response provided"),
        ("operational", "closed"): ("Closed", False, True, 100, "Closed"),
    }
    sm = {}
    for (domain, code), (name, is_initial, is_terminal, order, public_label) in statuses.items():
        sm[(domain, code)], _ = Status.objects.update_or_create(
            code=code,
            domain=domain,
            defaults={
                "name": name,
                "is_initial": is_initial,
                "is_terminal": is_terminal,
                "order": order,
                "public_label": public_label,
            },
        )
    transitions = [
        ("operational", "new", "triage", "Begin triage", False),
        ("operational", "triage", "assigned", "Assign", False),
        ("operational", "triage", "in_progress", "Start work", False),
        ("operational", "assigned", "in_progress", "Start work", False),
        ("operational", "triage", "escalated", "Escalate", False),
        ("operational", "assigned", "escalated", "Escalate", False),
        ("operational", "in_progress", "escalated", "Escalate", False),
        (
            "operational",
            "escalated",
            "in_progress",
            "Resume escalated work",
            False,
        ),
        ("operational", "in_progress", "resolved", "Resolve", True),
        ("operational", "resolved", "closed", "Close", False),
    ]
    for domain, frm, to, name, sets_res in transitions:
        Transition.objects.update_or_create(
            domain=domain,
            from_status=sm[(domain, frm)],
            to_status=sm[(domain, to)],
            defaults={
                "name": name,
                "sets_resolution": sets_res,
                "required_fields": ["reason"] if to == "escalated" else [],
                "is_active": True,
            },
        )
