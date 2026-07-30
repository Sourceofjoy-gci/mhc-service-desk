"""Deployment-safety checks for SLA schema migrations."""
from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_frozen_pause_microseconds_migration_round_trips_schema() -> None:
    """The nullable field must be safely removable and re-applicable."""
    before = [("sla", "0004_backfill_paused_remaining_business_seconds")]
    after = [("sla", "0005_frozen_pause_microseconds")]
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        before_apps = executor.loader.project_state(before).apps
        before_fields = {
            field.name for field in before_apps.get_model("sla", "SlaInstance")._meta.fields
        }
        assert "remaining_business_microseconds" not in before_fields

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        after_apps = executor.loader.project_state(after).apps
        after_fields = {
            field.name for field in after_apps.get_model("sla", "SlaInstance")._meta.fields
        }
        assert "remaining_business_microseconds" in after_fields

        executor = MigrationExecutor(connection)
        executor.migrate(before)
        reversed_apps = executor.loader.project_state(before).apps
        reversed_fields = {
            field.name
            for field in reversed_apps.get_model("sla", "SlaInstance")._meta.fields
        }
        assert "remaining_business_microseconds" not in reversed_fields
    finally:
        MigrationExecutor(connection).migrate(after)
