from django.db import migrations

OPERATIONAL_TRANSITION_REQUIRED_ROLES = {
    ("in_progress", "resolved"): "assistant-master",
    ("quality_review", "resolved"): "assistant-master",
    ("escalated", "in_progress"): "deputy-master",
    ("resolved", "reopened"): "deputy-master",
    ("resolved", "closed"): "master",
    ("cancelled", "closed"): "master",
    ("rejected", "closed"): "master",
    ("duplicate", "closed"): "master",
    ("spam", "closed"): "master",
}


def apply_internal_staff_transition_roles(apps, schema_editor):
    del schema_editor
    Transition = apps.get_model("workflow", "Transition")
    for (from_code, to_code), required_role in (
        OPERATIONAL_TRANSITION_REQUIRED_ROLES.items()
    ):
        Transition.objects.filter(
            domain="operational",
            from_status__code=from_code,
            to_status__code=to_code,
        ).update(required_role=required_role)


def remove_internal_staff_transition_roles(apps, schema_editor):
    del schema_editor
    Transition = apps.get_model("workflow", "Transition")
    for (from_code, to_code), required_role in (
        OPERATIONAL_TRANSITION_REQUIRED_ROLES.items()
    ):
        Transition.objects.filter(
            domain="operational",
            from_status__code=from_code,
            to_status__code=to_code,
            required_role=required_role,
        ).update(required_role="")


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0013_escalated_workflow"),
        ("workflow", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            apply_internal_staff_transition_roles,
            remove_internal_staff_transition_roles,
        ),
    ]
