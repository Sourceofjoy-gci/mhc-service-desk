from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0010_protect_ticket_queue"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketReferenceCounter",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "domain",
                    models.CharField(
                        choices=[("operational", "Operational"), ("it", "IT")],
                        max_length=16,
                    ),
                ),
                ("prefix", models.CharField(max_length=8)),
                ("period", models.CharField(max_length=6)),
                ("last_value", models.PositiveBigIntegerField(default=0)),
            ],
            options={"db_table": "ticket_reference_counter"},
        ),
        migrations.AddConstraint(
            model_name="ticketreferencecounter",
            constraint=models.UniqueConstraint(
                fields=("domain", "prefix", "period"),
                name="uniq_ticket_reference_counter_scope",
            ),
        ),
    ]
