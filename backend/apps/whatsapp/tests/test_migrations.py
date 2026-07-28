"""Deployment-safety checks for WhatsApp data migrations."""
from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_unique_provider_id_migration_preserves_rows_and_clears_duplicates() -> None:
    before = [("whatsapp", "0002_alter_whatsappmessage_account")]
    after = [("whatsapp", "0003_whatsappmessage_unique_external_id")]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    old_apps = executor.loader.project_state(before).apps
    account_model = old_apps.get_model("whatsapp", "WhatsappAccount")
    message_model = old_apps.get_model("whatsapp", "WhatsappMessage")
    account = account_model.objects.create(
        phone_number_id="migration-phone",
        display_name="Migration account",
        domain="operational",
        is_active=True,
    )
    for body in ("first", "duplicate"):
        message_model.objects.create(
            account=account,
            direction="inbound",
            body=body,
            external_message_id="wamid.preexisting-duplicate",
        )

    executor = MigrationExecutor(connection)
    executor.migrate(after)
    new_apps = executor.loader.project_state(after).apps
    migrated_message_model = new_apps.get_model("whatsapp", "WhatsappMessage")

    assert migrated_message_model.objects.count() == 2
    assert migrated_message_model.objects.filter(
        external_message_id="wamid.preexisting-duplicate"
    ).count() == 1
    assert migrated_message_model.objects.filter(external_message_id="").count() == 1
