"""Deployment-safety checks for WhatsApp data migrations."""

from __future__ import annotations

import pytest

PREVIOUS = "0002_alter_whatsappmessage_account"
SUBJECT = "0003_whatsappmessage_unique_external_id"


@pytest.mark.django_db(transaction=True)
def test_unique_provider_id_migration_preserves_rows_and_clears_duplicates(migrations) -> None:
    old_apps = migrations.migrate("whatsapp", PREVIOUS)
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

    migrated = migrations.migrate("whatsapp", SUBJECT).get_model("whatsapp", "WhatsappMessage")

    assert migrated.objects.count() == 2
    assert (
        migrated.objects.filter(external_message_id="wamid.preexisting-duplicate").count() == 1
    )
    assert migrated.objects.filter(external_message_id="").count() == 1
