"""Deployment-safety checks for SLA schema migrations."""

from __future__ import annotations

import pytest

PREVIOUS = "0004_backfill_paused_remaining_business_seconds"
SUBJECT = "0005_frozen_pause_microseconds"
FIELD = "remaining_business_microseconds"


def _field_names(apps) -> set[str]:
    return {field.name for field in apps.get_model("sla", "SlaInstance")._meta.fields}


@pytest.mark.django_db(transaction=True)
def test_frozen_pause_microseconds_migration_round_trips_schema(migrations) -> None:
    """The nullable field must be safely removable and re-applicable."""
    assert FIELD not in _field_names(migrations.migrate("sla", PREVIOUS))
    assert FIELD in _field_names(migrations.migrate("sla", SUBJECT))
    assert FIELD not in _field_names(migrations.migrate("sla", PREVIOUS))
