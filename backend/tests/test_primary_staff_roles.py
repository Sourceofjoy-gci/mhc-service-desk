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
    "records-clerk": "Records Clerk",
    "data-clerk": "Data Clerk",
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


@pytest.mark.django_db
def test_development_seed_preserves_existing_primary_role_configuration():
    existing_scopes = [{"domain": "operational", "office": "configured-office"}]
    existing = Role.objects.create(
        keycloak_role="master",
        name="Configured Master",
        scopes=existing_scopes,
    )

    seed_dev.seed_primary_staff_roles()

    existing.refresh_from_db()
    assert existing.name == "Configured Master"
    assert existing.scopes == existing_scopes


def test_keycloak_realm_declares_primary_roles_without_default_assignments():
    realm_path = Path(__file__).resolve().parents[2] / "infrastructure/keycloak/realm-mhc.json"
    realm = json.loads(realm_path.read_text(encoding="utf-8"))
    realm_roles = {
        role["name"]: role.get("description")
        for role in realm["roles"]["realm"]
        if role["name"] in PRIMARY_STAFF_ROLES
    }

    assert realm_roles == PRIMARY_STAFF_ROLES

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
