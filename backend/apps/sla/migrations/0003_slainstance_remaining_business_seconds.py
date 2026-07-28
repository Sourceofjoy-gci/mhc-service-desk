from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sla", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="slainstance",
            name="remaining_business_seconds",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
