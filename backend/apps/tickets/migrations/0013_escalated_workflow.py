from django.db import migrations


ESCALATION_FROM = {
    "operational": (
        "triage",
        "assigned",
        "in_progress",
        "waiting_requester",
        "waiting_internal",
        "waiting_it",
        "quality_review",
        "reopened",
    ),
    "it": (
        "triage",
        "assigned",
        "diagnosing",
        "in_progress",
        "waiting_user",
        "waiting_vendor",
        "waiting_change",
        "validation",
        "reopened",
    ),
}


def add_escalated_workflow(apps, schema_editor):
    del schema_editor
    Status = apps.get_model("workflow", "Status")
    Transition = apps.get_model("workflow", "Transition")

    for domain, from_codes in ESCALATION_FROM.items():
        escalated, _ = Status.objects.update_or_create(
            domain=domain,
            code="escalated",
            defaults={
                "name": "Escalated",
                "is_initial": False,
                "is_terminal": False,
                "order": 85,
                "public_label": "Escalated for attention",
            },
        )
        in_progress = Status.objects.filter(
            domain=domain,
            code="in_progress",
        ).first()
        if in_progress is not None:
            Transition.objects.update_or_create(
                domain=domain,
                from_status=escalated,
                to_status=in_progress,
                defaults={
                    "name": "Resume escalated work",
                    "required_fields": [],
                    "sets_resolution": False,
                    "is_active": True,
                },
            )
        for from_status in Status.objects.filter(
            domain=domain,
            code__in=from_codes,
        ):
            Transition.objects.update_or_create(
                domain=domain,
                from_status=from_status,
                to_status=escalated,
                defaults={
                    "name": "Escalate",
                    "required_fields": ["reason"],
                    "sets_resolution": False,
                    "is_active": True,
                },
            )


def disable_escalated_workflow(apps, schema_editor):
    del schema_editor
    Status = apps.get_model("workflow", "Status")
    Transition = apps.get_model("workflow", "Transition")
    escalated_ids = Status.objects.filter(code="escalated").values_list(
        "id",
        flat=True,
    )
    Transition.objects.filter(to_status_id__in=escalated_ids).update(is_active=False)
    Transition.objects.filter(from_status_id__in=escalated_ids).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0012_ticket_reference_immutable"),
        ("workflow", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            add_escalated_workflow,
            disable_escalated_workflow,
        ),
    ]
