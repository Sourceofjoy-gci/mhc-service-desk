"""Require the approved retention gate for custody cascades."""

from django.db import migrations, models


def require_retention_gate(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ticket_custody_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND current_setting('mhc.allow_ticket_custody_delete', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'ticket custody events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def restore_parent_delete_check(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ticket_custody_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND NOT EXISTS (
               SELECT 1 FROM ticket WHERE id = OLD.ticket_id
             ) THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'ticket custody events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0007_ticket_custody_collector_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticketcustodyevent",
            name="actor_kind",
            field=models.CharField(
                choices=[
                    ("user", "User"),
                    ("system", "System"),
                    ("legacy_unknown", "Legacy actor (unverified)"),
                ],
                max_length=16,
            ),
        ),
        migrations.RunPython(require_retention_gate, restore_parent_delete_check),
    ]
