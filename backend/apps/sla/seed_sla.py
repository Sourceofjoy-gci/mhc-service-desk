"""Seed default business calendars and SLA policies (P0 targets from PRD §17)."""
from __future__ import annotations

from apps.sla.models import BusinessCalendar, SlaPolicy


def seed_sla() -> None:
    cal, _ = BusinessCalendar.objects.update_or_create(
        name="Eswatini business hours",
        defaults={
            "timezone": "Africa/Mbabane",
            "weekday_hours": {
                "1": [{"start": "08:00", "end": "17:00"}],
                "2": [{"start": "08:00", "end": "17:00"}],
                "3": [{"start": "08:00", "end": "17:00"}],
                "4": [{"start": "08:00", "end": "17:00"}],
                "5": [{"start": "08:00", "end": "17:00"}],
                "6": [],
                "7": [],
            },
            "holidays": [
                "2026-01-01", "2026-01-02",
                "2026-04-03", "2026-04-04", "2026-04-05", "2026-04-06",
                "2026-04-25",
                "2026-05-01",
                "2026-07-22",
                "2026-09-06",
                "2026-12-25", "2026-12-26",
            ],
            "is_default": True,
        },
    )

    # Operational targets (PRD §17.2)
    op_targets = {
        "P1": (0, 30, 120, 8 * 60, 75, 90),
        "P2": (0, 120, 1440, 2 * 24 * 60, 75, 90),
        "P3": (0, 480, 2880, 5 * 24 * 60, 75, 90),
        "P4": (0, 960, 7200, 10 * 24 * 60, 75, 90),
    }
    for prio, (ack, first, upd, res, warn, esc) in op_targets.items():
        SlaPolicy.objects.update_or_create(
            name=f"Operational {prio}",
            domain="operational",
            priority=prio,
            defaults={
                "calendar": cal,
                "acknowledgement_minutes": ack,
                "first_response_minutes": first,
                "update_interval_minutes": upd,
                "resolution_minutes": res,
                "warn_at_percent": warn,
                "escalation_percent": esc,
                "is_active": True,
            },
        )

    # IT targets (PRD §17.3)
    it_targets = {
        "P1": (0, 15, 120, 240, 75, 90),
        "P2": (0, 30, 240, 1440, 75, 90),
        "P3": (0, 240, 1440, 3 * 1440, 75, 90),
        "P4": (0, 1440, 1440 * 5, 5 * 1440, 75, 90),
    }
    for prio, (ack, first, upd, res, warn, esc) in it_targets.items():
        SlaPolicy.objects.update_or_create(
            name=f"IT {prio}",
            domain="it",
            priority=prio,
            defaults={
                "calendar": cal,
                "acknowledgement_minutes": ack,
                "first_response_minutes": first,
                "update_interval_minutes": upd,
                "resolution_minutes": res,
                "warn_at_percent": warn,
                "escalation_percent": esc,
                "is_active": True,
            },
        )
