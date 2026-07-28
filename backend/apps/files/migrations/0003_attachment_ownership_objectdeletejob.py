from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0002_disposalevent"),
        ("files", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="attachment",
            name="object_bucket",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="attachment",
            name="object_etag",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="attachment",
            name="object_version_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.CreateModel(
            name="ObjectDeleteJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True,
                        serialize=False,
                    ),
                ),
                ("source_attachment_id", models.UUIDField()),
                ("bucket", models.CharField(max_length=255)),
                ("object_key", models.CharField(max_length=512)),
                ("version_id", models.CharField(max_length=255)),
                ("etag", models.CharField(blank=True, max_length=255)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField()),
                ("last_error_code", models.CharField(blank=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "disposal_event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="object_delete_jobs",
                        to="administration.disposalevent",
                    ),
                ),
            ],
            options={"db_table": "file_object_delete_job"},
        ),
        migrations.AddConstraint(
            model_name="objectdeletejob",
            constraint=models.UniqueConstraint(
                fields=("bucket", "object_key", "version_id"),
                name="uniq_object_delete_exact_version",
            ),
        ),
        migrations.AddIndex(
            model_name="objectdeletejob",
            index=models.Index(
                fields=["completed_at", "next_attempt_at"],
                name="file_object_complet_162b7a_idx",
            ),
        ),
    ]
