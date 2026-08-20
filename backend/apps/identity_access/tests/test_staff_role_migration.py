from __future__ import annotations

import pytest

PREVIOUS = "0002_user_groups"
SUBJECT = "0003_internal_staff_roles"


@pytest.mark.django_db(transaction=True)
def test_internal_staff_role_migration_adds_missing_roles_and_preserves_configuration(
    migrations,
):
    expected_descriptions = {
        "records-officer": (
            "Register new estate matters; capture metadata; receive and index "
            "documents; maintain file completeness. Authority: Create and update "
            "case intake records."
        ),
        "examiner": (
            "Review estate submissions; verify documents; raise defects; assess "
            "compliance. Authority: Review and recommend."
        ),
        "assistant-master": (
            "Supervise reviews; validate recommendations; authorise workflow "
            "progress. Authority: Approve within delegated authority."
        ),
        "deputy-master": (
            "Perform higher-level review; handle exceptions; make escalation "
            "decisions. Authority: Senior approval and oversight."
        ),
        "master": (
            "Make final decisions on designated approvals and policy exceptions. "
            "Authority: Full approval authority."
        ),
    }

    old_apps = migrations.migrate("identity_access", PREVIOUS)
    old_role = old_apps.get_model("identity_access", "Role")
    old_role.objects.filter(keycloak_role__in=expected_descriptions).delete()
    old_role.objects.create(
        keycloak_role="master",
        name="Configured Master",
        description="",
        scopes=[{"domain": "operational", "office": "configured-office"}],
    )

    new_apps = migrations.migrate("identity_access", SUBJECT)
    migrated_role = new_apps.get_model("identity_access", "Role")
    roles = {
        role.keycloak_role: role
        for role in migrated_role.objects.filter(
            keycloak_role__in=expected_descriptions,
        )
    }

    assert set(roles) == set(expected_descriptions)
    assert roles["master"].name == "Configured Master"
    assert roles["master"].scopes == [{"domain": "operational", "office": "configured-office"}]
    assert {
        role_key: role.description for role_key, role in roles.items()
    } == expected_descriptions
    assert all(
        role.scopes == [{"domain": "operational"}]
        for role_key, role in roles.items()
        if role_key != "master"
    )
