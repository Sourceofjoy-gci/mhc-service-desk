import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0009_protect_ticket_assignee"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticket",
            name="queue",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tickets",
                to="organisations.servicelocation",
            ),
        ),
    ]
