from __future__ import annotations

from django.db import migrations, models


def normalize_delivery_event_types(apps, schema_editor) -> None:
    event_model = apps.get_model("email_channel", "EmailWebhookEvent")
    event_model.objects.filter(event_type="bounce").update(
        event_type="delivery_bounce"
    )


def restore_legacy_delivery_event_types(apps, schema_editor) -> None:
    event_model = apps.get_model("email_channel", "EmailWebhookEvent")
    event_model.objects.filter(event_type="delivery_failure").update(
        event_type="failure"
    )
    event_model.objects.filter(event_type="delivery_bounce").update(
        event_type="bounce"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("email_channel", "0002_emailwebhookevent"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="emailwebhookevent",
            name="uniq_email_webhook_type_message_when_set",
        ),
        migrations.RunPython(
            normalize_delivery_event_types,
            restore_legacy_delivery_event_types,
        ),
        migrations.AlterField(
            model_name="emailwebhookevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("inbound", "Inbound"),
                    ("delivery_failure", "Delivery failure"),
                    ("delivery_bounce", "Delivery bounce"),
                ],
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="emailwebhookevent",
            constraint=models.UniqueConstraint(
                condition=~models.Q(message_id=""),
                fields=("event_type", "message_id"),
                name="uniq_email_event_type_message_when_set_v2",
            ),
        ),
        migrations.AddConstraint(
            model_name="emailwebhookevent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    event_type__in=(
                        "inbound",
                        "delivery_failure",
                        "delivery_bounce",
                    )
                ),
                name="email_event_type_is_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="emailwebhookevent",
            constraint=models.CheckConstraint(
                condition=~models.Q(message_id=""),
                name="email_event_message_id_not_blank",
            ),
        ),
    ]
