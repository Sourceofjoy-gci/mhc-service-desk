from __future__ import annotations

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("administration", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="DisposalEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True,
                        serialize=False,
                    ),
                ),
                ("policy_snapshot", models.JSONField()),
                ("policy_hash", models.CharField(max_length=64)),
                ("summary", models.JSONField()),
                ("summary_hash", models.CharField(max_length=64)),
                ("certificate_path", models.CharField(max_length=1024)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "object_cleanup_completed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "certificate_exported_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("export_error", models.CharField(blank=True, max_length=128)),
            ],
            options={
                "db_table": "administration_disposal_event",
                "ordering": ("-created_at",),
            },
        )
    ]
