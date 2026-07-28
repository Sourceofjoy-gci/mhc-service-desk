"""Deployment-safety checks for email channel data migrations."""
from __future__ import annotations

import pytest
from django.db import IntegrityError, connection, transaction
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


@pytest.mark.django_db(transaction=True)
def test_delivery_event_migration_round_trips_failure_and_bounce_receipts() -> None:
    before = [("email_channel", "0002_emailwebhookevent")]
    after = [("email_channel", "0003_distinguish_delivery_webhook_events")]
    message_id = "<round-trip@example.com>"
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    legacy_apps = executor.loader.project_state(before).apps
    legacy_event_model = legacy_apps.get_model(
        "email_channel",
        "EmailWebhookEvent",
    )
    legacy_event_model.objects.create(
        event_id="legacy-failure",
        event_type="failure",
        message_id=message_id,
    )
    legacy_event_model.objects.create(
        event_id="legacy-bounce",
        event_type="bounce",
        message_id=message_id,
    )

    executor = MigrationExecutor(connection)
    executor.migrate(after)
    migrated_apps = executor.loader.project_state(after).apps
    migrated_event_model = migrated_apps.get_model(
        "email_channel",
        "EmailWebhookEvent",
    )
    assert dict(
        migrated_event_model.objects.values_list("event_id", "event_type")
    ) == {
        "legacy-failure": "delivery_failure",
        "legacy-bounce": "delivery_bounce",
    }

    executor = MigrationExecutor(connection)
    executor.migrate(before)
    reversed_apps = executor.loader.project_state(before).apps
    reversed_event_model = reversed_apps.get_model(
        "email_channel",
        "EmailWebhookEvent",
    )
    assert dict(
        reversed_event_model.objects.values_list("event_id", "event_type")
    ) == {
        "legacy-failure": "failure",
        "legacy-bounce": "bounce",
    }

    executor = MigrationExecutor(connection)
    executor.migrate(after)
    reapplied_apps = executor.loader.project_state(after).apps
    reapplied_event_model = reapplied_apps.get_model(
        "email_channel",
        "EmailWebhookEvent",
    )
    assert dict(
        reapplied_event_model.objects.values_list("event_id", "event_type")
    ) == {
        "legacy-failure": "delivery_failure",
        "legacy-bounce": "delivery_bounce",
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        reapplied_event_model.objects.create(
            event_id="replayed-failure-with-new-event-id",
            event_type="delivery_failure",
            message_id=message_id,
        )
