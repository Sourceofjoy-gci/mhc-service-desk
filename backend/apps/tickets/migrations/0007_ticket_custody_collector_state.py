from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0006_backfill_ticket_custody"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterModelOptions(
                    name="ticket",
                    options={
                        "base_manager_name": "objects",
                        "ordering": ("-created_at",),
                    },
                ),
                migrations.AlterField(
                    model_name="ticketcustodyevent",
                    name="ticket",
                    field=models.ForeignKey(
                        on_delete=models.DO_NOTHING,
                        related_name="custody_events",
                        to="tickets.ticket",
                    ),
                ),
            ],
        ),
    ]
