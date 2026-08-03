from django.db import migrations


INTERNAL_STAFF_ROLES = (
    (
        "records-officer",
        "Records Officer",
        "Register new estate matters; capture metadata; receive and index "
        "documents; maintain file completeness. Authority: Create and update "
        "case intake records.",
    ),
    (
        "examiner",
        "Examiner",
        "Review estate submissions; verify documents; raise defects; assess "
        "compliance. Authority: Review and recommend.",
    ),
    (
        "assistant-master",
        "Assistant Master",
        "Supervise reviews; validate recommendations; authorise workflow "
        "progress. Authority: Approve within delegated authority.",
    ),
    (
        "deputy-master",
        "Deputy Master",
        "Perform higher-level review; handle exceptions; make escalation "
        "decisions. Authority: Senior approval and oversight.",
    ),
    (
        "master",
        "Master",
        "Make final decisions on designated approvals and policy exceptions. "
        "Authority: Full approval authority.",
    ),
)


def add_internal_staff_roles(apps, schema_editor):
    del schema_editor
    Role = apps.get_model("identity_access", "Role")
    for role_key, display_name, description in INTERNAL_STAFF_ROLES:
        role, created = Role.objects.get_or_create(
            keycloak_role=role_key,
            defaults={
                "name": display_name,
                "description": description,
                "scopes": [{"domain": "operational"}],
            },
        )
        if not created and not role.description.strip():
            role.description = description
            role.save(update_fields=["description", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("identity_access", "0002_user_groups"),
    ]

    operations = [
        migrations.RunPython(add_internal_staff_roles, migrations.RunPython.noop),
    ]
