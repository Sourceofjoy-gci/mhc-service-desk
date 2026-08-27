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
    """Keycloak ignores the realm export's top-level ``protocolMappers`` array on

    import — a mapper only takes effect on tokens when it lives inside a client
    scope that a client actually carries. ``mhc-frontend`` defaults to the
    ``profile`` scope, so that's where these mappers must live.
    """
    realm = _realm()
    top_level_names = {m["name"] for m in realm["protocolMappers"]}
    for name in ("office", "station"):
        assert name not in top_level_names, (
            f"'{name}' is declared in the realm's top-level protocolMappers array, "
            "which Keycloak ignores on import — it must live in a client scope "
            "instead (see the 'profile' client scope)"
        )

    profile_scope = next(s for s in realm["clientScopes"] if s["name"] == "profile")
    mappers = {m["name"]: m for m in profile_scope["protocolMappers"]}
    for name, attribute in (("office", "office"), ("station", "station")):
        assert name in mappers, f"missing protocol mapper in 'profile' client scope: {name}"
        mapper = mappers[name]
        assert mapper["protocolMapper"] == "oidc-usermodel-attribute-mapper"
        assert mapper["config"]["user.attribute"] == attribute
        assert mapper["config"]["claim.name"] == attribute
        assert mapper["config"]["access.token.claim"] == "true"

    frontend_client = next(c for c in realm["clients"] if c["clientId"] == "mhc-frontend")
    assert "profile" in frontend_client["defaultClientScopes"], (
        "'profile' must stay a default client scope of mhc-frontend for the "
        "office/station mappers to reach a real token"
    )


def test_service_desk_group_and_realm_role_exist():
    realm = _realm()
    groups = {g["name"]: g for g in realm["groups"]}
    assert "service-desk-agents" in groups
    assert set(groups["service-desk-agents"]["realmRoles"]) == {"staff", "agent-servicedesk"}
    assert "agent-servicedesk" in {r["name"] for r in realm["roles"]["realm"]}


def test_frontend_client_allows_local_lan_and_public_origins():
    """Every supported entry point must survive the OIDC redirect round trip."""
    realm = _realm()
    frontend_client = next(c for c in realm["clients"] if c["clientId"] == "mhc-frontend")

    assert set(frontend_client["redirectUris"]) == {
        "${LOCAL_BASE_URL}/*",
        "${LAN_BASE_URL}/*",
        "${PUBLIC_BASE_URL}/*",
    }
    assert set(frontend_client["webOrigins"]) == {
        "${LOCAL_BASE_URL}",
        "${LAN_BASE_URL}",
        "${PUBLIC_BASE_URL}",
    }


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
