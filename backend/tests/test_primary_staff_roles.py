from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.identity_access.models import Role
from scripts import seed_dev

PRIMARY_STAFF_ROLES = {
    "master": "Master",
    "deputy-master": "Deputy Master",
    "assistant-master": "Assistant Master",
    "assistant-accountant": "Assistant Accountant",
    "accountant": "Accountant",
    "senior-accountant": "Senior Accountant",
    "principal-accountant": "Principal Accountant",
    "financial-controller": "Financial Controller",
    "estate-examiner": "Estate Examiner",
    "examiner": "Examiner",
    "records-clerk": "Records Clerk",
    "records-officer": "Records Officer",
    "data-clerk": "Data Clerk",
}

TECHNICAL_REALM_ROLES = {
    "staff",
    "agent-operational",
    "supervisor-operational",
    "agent-it",
    "lead-it",
    "admin",
    "auditor",
}

INTERNAL_STAFF_CONTEXT = {
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


@pytest.mark.django_db
def test_development_seed_creates_all_primary_staff_roles():
    seed_dev.seed_primary_staff_roles()

    seeded = {
        role.keycloak_role: (role.name, role.scopes)
        for role in Role.objects.filter(keycloak_role__in=PRIMARY_STAFF_ROLES)
    }
    assert seeded == {
        role_key: (display_name, [{"domain": "operational"}])
        for role_key, display_name in PRIMARY_STAFF_ROLES.items()
    }
    assert {
        role.keycloak_role: role.description
        for role in Role.objects.filter(keycloak_role__in=INTERNAL_STAFF_CONTEXT)
    } == INTERNAL_STAFF_CONTEXT


@pytest.mark.django_db
def test_development_seed_preserves_existing_primary_role_configuration():
    existing_scopes = [{"domain": "operational", "office": "configured-office"}]
    existing, _ = Role.objects.update_or_create(
        keycloak_role="master",
        defaults={
            "name": "Configured Master",
            "description": "",
            "scopes": existing_scopes,
        },
    )

    seed_dev.seed_primary_staff_roles()

    existing.refresh_from_db()
    assert existing.name == "Configured Master"
    assert existing.scopes == existing_scopes


def test_keycloak_realm_declares_primary_roles_without_default_assignments():
    realm_path = Path(__file__).resolve().parents[2] / "infrastructure/keycloak/realm-mhc.json"
    realm = json.loads(realm_path.read_text(encoding="utf-8"))
    declared_role_keys = {role["name"] for role in realm["roles"]["realm"]}
    assert declared_role_keys == set(PRIMARY_STAFF_ROLES) | TECHNICAL_REALM_ROLES

    realm_roles = {
        role["name"]: role
        for role in realm["roles"]["realm"]
        if role["name"] in PRIMARY_STAFF_ROLES
    }

    assert set(realm_roles) == set(PRIMARY_STAFF_ROLES)
    assert {
        role_key: role.get("description")
        for role_key, role in realm_roles.items()
        if role_key in INTERNAL_STAFF_CONTEXT
    } == INTERNAL_STAFF_CONTEXT

    default_group_roles = {
        role
        for group in realm.get("groups", [])
        for role in group.get("realmRoles", [])
    }
    default_user_roles = {
        role
        for user in realm.get("users", [])
        for role in user.get("realmRoles", [])
    }
    assert set(PRIMARY_STAFF_ROLES).isdisjoint(default_group_roles)
    assert set(PRIMARY_STAFF_ROLES).isdisjoint(default_user_roles)


def test_frontend_client_includes_realm_roles_in_staff_tokens():
    realm_path = Path(__file__).resolve().parents[2] / "infrastructure/keycloak/realm-mhc.json"
    realm = json.loads(realm_path.read_text(encoding="utf-8"))
    frontend_client = next(
        client for client in realm["clients"] if client["clientId"] == "mhc-frontend"
    )

    assert "roles" in frontend_client["defaultClientScopes"]

    roles_scope = next(scope for scope in realm["clientScopes"] if scope["name"] == "roles")
    realm_roles_mapper = next(
        mapper
        for mapper in roles_scope["protocolMappers"]
        if mapper["protocolMapper"] == "oidc-usermodel-realm-role-mapper"
    )
    assert realm_roles_mapper["config"] == {
        "user.attribute": "foo",
        "introspection.token.claim": "true",
        "access.token.claim": "true",
        "claim.name": "realm_access.roles",
        "jsonType.label": "String",
        "multivalued": "true",
    }
