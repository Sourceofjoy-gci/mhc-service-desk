"""The realm export is the source of truth for office claims and staff roles."""

from __future__ import annotations

import json
from pathlib import Path

REALM_PATH = Path(__file__).resolve().parents[4] / "infrastructure/keycloak/realm-mhc.json"


def _realm() -> dict:
    return json.loads(REALM_PATH.read_text(encoding="utf-8"))


def test_realm_export_is_readable():
    assert REALM_PATH.is_file(), f"realm export not found at {REALM_PATH}"


def test_office_and_station_attribute_mappers_exist():
    mappers = {m["name"]: m for m in _realm()["protocolMappers"]}
    for name, attribute in (("office", "office"), ("station", "station")):
        assert name in mappers, f"missing protocol mapper: {name}"
        mapper = mappers[name]
        assert mapper["protocolMapper"] == "oidc-usermodel-attribute-mapper"
        assert mapper["config"]["user.attribute"] == attribute
        assert mapper["config"]["claim.name"] == attribute
        assert mapper["config"]["access.token.claim"] == "true"


def test_service_desk_group_and_realm_role_exist():
    realm = _realm()
    groups = {g["name"]: g for g in realm["groups"]}
    assert "service-desk-agents" in groups
    assert set(groups["service-desk-agents"]["realmRoles"]) == {"staff", "agent-servicedesk"}
    assert "agent-servicedesk" in {r["name"] for r in realm["roles"]["realm"]}


def _user_profile() -> dict:
    """Parse the declarative User Profile out of the realm's components block.

    Keycloak 24+ silently drops any user attribute not declared here on write,
    regardless of what the protocol mappers claim to expose — so the mappers
    alone (see test_office_and_station_attribute_mappers_exist) are not enough.
    """
    realm = _realm()
    providers = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
    config_json = providers[0]["config"]["kc.user.profile.config"][0]
    assert isinstance(config_json, str), "kc.user.profile.config must be a serialised JSON string"
    return json.loads(config_json)


def test_office_and_station_are_declared_managed_attributes():
    profile = _user_profile()
    attributes = {a["name"]: a for a in profile["attributes"]}
    for name in ("office", "station"):
        assert name in attributes, (
            f"'{name}' is not declared in the User Profile — Keycloak will silently "
            "drop it on write even though a protocol mapper exists for it"
        )


def test_office_and_station_are_not_user_editable():
    profile = _user_profile()
    attributes = {a["name"]: a for a in profile["attributes"]}
    for name in ("office", "station"):
        edit_roles = set(attributes[name]["permissions"]["edit"])
        assert "user" not in edit_roles, (
            f"'{name}' grants edit to 'user' — an officer could self-assign their "
            "own office, which determines what they are authorised to see"
        )
        assert "admin" in edit_roles
