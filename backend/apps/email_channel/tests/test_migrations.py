"""Deployment-safety checks for email channel data migrations."""
from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_delivery_event_migration_normalizes_legacy_bounce_receipts() -> None:
    before = [("email_channel", "0002_emailwebhookevent")]
    after = [("email_channel", "0003_distinguish_delivery_webhook_events")]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    old_apps = executor.loader.project_state(before).apps
    event_model = old_apps.get_model("email_channel", "EmailWebhookEvent")
    event_model.objects.create(
        event_id="legacy-event-id",
        event_type="bounce",
        message_id="<legacy@example.com>",
    )

    executor = MigrationExecutor(connection)
    executor.migrate(after)
    new_apps = executor.loader.project_state(after).apps
    migrated_event_model = new_apps.get_model(
        "email_channel",
        "EmailWebhookEvent",
    )

    migrated = migrated_event_model.objects.get(event_id="legacy-event-id")
    assert migrated.event_type == "delivery_bounce"
