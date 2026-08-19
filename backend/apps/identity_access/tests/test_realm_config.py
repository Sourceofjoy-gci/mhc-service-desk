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
