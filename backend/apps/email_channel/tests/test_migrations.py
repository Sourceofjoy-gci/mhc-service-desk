"""Deployment-safety checks for email channel data migrations."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

PREVIOUS = "0002_emailwebhookevent"
SUBJECT = "0003_distinguish_delivery_webhook_events"


def _event_model(apps):
    return apps.get_model("email_channel", "EmailWebhookEvent")


@pytest.mark.django_db(transaction=True)
def test_delivery_event_migration_normalizes_legacy_bounce_receipts(migrations) -> None:
    legacy = _event_model(migrations.migrate("email_channel", PREVIOUS))
    legacy.objects.create(
        event_id="legacy-event-id",
        event_type="bounce",
        message_id="<legacy@example.com>",
    )

    migrated = _event_model(migrations.migrate("email_channel", SUBJECT))

    assert migrated.objects.get(event_id="legacy-event-id").event_type == "delivery_bounce"


@pytest.mark.django_db(transaction=True)
def test_delivery_event_migration_round_trips_failure_and_bounce_receipts(migrations) -> None:
    message_id = "<round-trip@example.com>"
    legacy = _event_model(migrations.migrate("email_channel", PREVIOUS))
    legacy.objects.create(
        event_id="legacy-failure",
        event_type="failure",
        message_id=message_id,
    )
    legacy.objects.create(
        event_id="legacy-bounce",
        event_type="bounce",
        message_id=message_id,
    )

    migrated = _event_model(migrations.migrate("email_channel", SUBJECT))
    assert dict(migrated.objects.values_list("event_id", "event_type")) == {
        "legacy-failure": "delivery_failure",
        "legacy-bounce": "delivery_bounce",
    }

    reversed_model = _event_model(migrations.migrate("email_channel", PREVIOUS))
    assert dict(reversed_model.objects.values_list("event_id", "event_type")) == {
        "legacy-failure": "failure",
        "legacy-bounce": "bounce",
    }

    reapplied = _event_model(migrations.migrate("email_channel", SUBJECT))
    assert dict(reapplied.objects.values_list("event_id", "event_type")) == {
        "legacy-failure": "delivery_failure",
        "legacy-bounce": "delivery_bounce",
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        reapplied.objects.create(
            event_id="replayed-failure-with-new-event-id",
            event_type="delivery_failure",
            message_id=message_id,
        )
