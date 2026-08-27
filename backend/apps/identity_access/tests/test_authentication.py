from unittest.mock import patch

import pytest
from django.conf import settings
from django.test import override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from apps.identity_access.authentication import (
    JSONObject,
    KeycloakJWTAuthentication,
    _verify_jwt,
)
from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import Scope, get_user_scopes
from config.settings.dev import _patch_dev_auth

pytestmark = pytest.mark.django_db


def test_jwt_verification_requires_the_configured_keycloak_issuer():
    with patch(
        "jwt.decode",
        return_value={"sub": "subject", "iss": "https://idp.example.test/realms/mhc"},
    ) as decode:
        _verify_jwt(
            "signed-token",
            object(),  # type: ignore[arg-type]
            audience="mhc-backend",
            issuer="https://idp.example.test/realms/mhc",
        )

    assert decode.call_args.kwargs["issuer"] == "https://idp.example.test/realms/mhc"
    assert decode.call_args.kwargs["options"]["verify_iss"] is True


def test_authentication_accepts_only_the_explicitly_configured_issuer_set():
    request = APIRequestFactory().get(
        "/api/v1/tickets/",
        HTTP_AUTHORIZATION="Bearer signed-token",
    )
    accepted_issuers = (
        "http://localhost:5173/realms/mhc",
        "http://192.168.3.34:5173/realms/mhc",
    )
    keycloak_settings = {**settings.KEYCLOAK, "ISSUERS": accepted_issuers}

    with (
        override_settings(KEYCLOAK=keycloak_settings),
        patch("apps.identity_access.authentication.AccessToken"),
        patch(
            "apps.identity_access.authentication._decode_unverified_header",
            return_value={"alg": "RS256", "kid": "key-1", "typ": "JWT"},
        ),
        patch(
            "apps.identity_access.authentication._get_jwks",
            return_value={"keys": [{"kid": "key-1"}]},
        ),
        patch(
            "apps.identity_access.authentication._build_public_key",
            return_value=object(),
        ),
        patch(
            "apps.identity_access.authentication._verify_jwt",
            return_value={"sub": "multi-origin-user"},
        ) as verify,
    ):
        KeycloakJWTAuthentication().authenticate(request)

    assert verify.call_args.kwargs["issuer"] == accepted_issuers


def _authenticate_verified_payload(payload: JSONObject) -> tuple[User, JSONObject]:
    request = APIRequestFactory().get(
        "/api/v1/tickets/",
        HTTP_AUTHORIZATION="Bearer signed-token",
    )
    with (
        patch("apps.identity_access.authentication.AccessToken"),
        patch(
            "apps.identity_access.authentication._decode_unverified_header",
            return_value={"alg": "RS256", "kid": "key-1", "typ": "JWT"},
        ),
        patch(
            "apps.identity_access.authentication._get_jwks",
            return_value={
                "keys": [
                    {
                        "alg": "RS256",
                        "e": "AQAB",
                        "kid": "key-1",
                        "kty": "RSA",
                        "n": "test-modulus",
                        "use": "sig",
                    }
                ]
            },
        ),
        patch(
            "apps.identity_access.authentication._build_public_key",
            return_value=object(),
        ),
        patch(
            "apps.identity_access.authentication._verify_jwt",
            return_value=payload,
        ),
    ):
        result = KeycloakJWTAuthentication().authenticate(request)
    assert result is not None
    return result


def test_dev_token_is_accepted_only_in_debug_mode():
    request = APIRequestFactory().get(
        "/api/v1/tickets/",
        HTTP_AUTHORIZATION="Bearer dev:pilot:ops-agents",
    )
    authenticator = KeycloakJWTAuthentication()

    with override_settings(DEBUG=True):
        user, payload = authenticator.authenticate(request)

    assert user.username == "pilot"
    assert user._groups == ["ops-agents"]
    assert payload["groups"] == ["ops-agents"]

    with (
        override_settings(DEBUG=False),
        patch(
            "apps.identity_access.authentication._get_jwks",
            side_effect=AssertionError("production-mode dev token attempted JWKS access"),
        ),
        pytest.raises(AuthenticationFailed),
    ):
        authenticator.authenticate(request)


def test_dev_auth_patch_delegates_without_recursing():
    request = APIRequestFactory().get(
        "/api/v1/tickets/",
        HTTP_AUTHORIZATION="Bearer dev:patched:ops-agents",
    )
    original_authenticate = KeycloakJWTAuthentication.authenticate

    try:
        _patch_dev_auth()
        with override_settings(DEBUG=True):
            user, payload = KeycloakJWTAuthentication().authenticate(request)
    finally:
        KeycloakJWTAuthentication.authenticate = original_authenticate

    assert user.username == "patched"
    assert payload["groups"] == ["ops-agents"]


def test_verified_token_rejects_an_inactive_local_user_without_refreshing_authority():
    user = User.objects.create(
        username="disabled-agent",
        keycloak_subject="disabled-subject",
        email="old@example.test",
        is_active=False,
        keycloak_groups=["ops-agents"],
    )

    with pytest.raises(AuthenticationFailed):
        _authenticate_verified_payload(
            {
                "sub": "disabled-subject",
                "preferred_username": "disabled-agent",
                "email": "new@example.test",
                "groups": ["system-admins"],
                "acr": "mfa",
                "iss": "https://idp.example.test/realms/mhc",
                "aud": "mhc-ticketing",
                "iat": 1_750_000_000,
                "exp": 1_750_000_300,
            }
        )

    user.refresh_from_db()
    assert user.email == "old@example.test"
    assert user.keycloak_groups == ["ops-agents"]
    assert not hasattr(user, "_groups")


def test_dev_token_rejects_an_inactive_local_user_without_refreshing_authority():
    user = User.objects.create(
        username="disabled-dev",
        keycloak_subject="dev:disabled-dev",
        is_active=False,
        keycloak_groups=["ops-agents"],
    )
    request = APIRequestFactory().get(
        "/api/v1/tickets/",
        HTTP_AUTHORIZATION="Bearer dev:disabled-dev:system-admins",
    )

    with override_settings(DEBUG=True), pytest.raises(AuthenticationFailed):
        KeycloakJWTAuthentication().authenticate(request)

    user.refresh_from_db()
    assert user.keycloak_groups == ["ops-agents"]
    assert not hasattr(user, "_groups")


def test_new_subject_cannot_relink_an_authoritative_username():
    user = User.objects.create(
        username="court-admin",
        keycloak_subject="established-subject",
        email="established@example.test",
        is_superuser=True,
        keycloak_groups=["system-admins"],
    )
    role = Role.objects.create(keycloak_role="admin", name="Administrator")
    UserRole.objects.create(user=user, role=role)

    with pytest.raises(AuthenticationFailed):
        _authenticate_verified_payload(
            {
                "sub": "unreconciled-new-subject",
                "preferred_username": "court-admin",
                "email": "attacker@example.test",
                "groups": ["system-admins"],
                "acr": "mfa",
                "iss": "https://idp.example.test/realms/mhc",
                "aud": "mhc-ticketing",
                "iat": 1_750_000_000,
                "exp": 1_750_000_300,
            }
        )

    user.refresh_from_db()
    assert user.keycloak_subject == "established-subject"
    assert user.email == "established@example.test"
    assert User.objects.count() == 1
    assert UserRole.objects.filter(user=user, role=role).exists()


def test_verified_token_safely_provisions_a_first_time_username():
    user, payload = _authenticate_verified_payload(
        {
            "sub": "first-time-subject",
            "preferred_username": "first-time-agent",
            "email": "first-time@example.test",
            "groups": ["ops-agents"],
            "acr": "mfa",
            "iss": "https://idp.example.test/realms/mhc",
            "aud": "mhc-ticketing",
            "iat": 1_750_000_000,
            "exp": 1_750_000_300,
        }
    )

    assert user.is_active
    assert user.keycloak_subject == "first-time-subject"
    assert user.username == "first-time-agent"
    assert user.email == "first-time@example.test"
    assert user.keycloak_groups == ["ops-agents"]
    assert user._groups == ["ops-agents"]
    assert payload["sub"] == "first-time-subject"


def test_verified_token_uses_realm_roles_for_staff_authorisation(basic_world):
    office = basic_world["office"]
    user, _ = _authenticate_verified_payload(
        {
            "sub": "realm-role-subject",
            "preferred_username": "realm-role-agent",
            "email": "realm-role-agent@example.test",
            "groups": ["/ops-agents"],
            "realm_access": {"roles": ["agent-it", "ops-agents"]},
            "office": office.code,
            "acr": "mfa",
            "iss": "https://idp.example.test/realms/mhc",
            "aud": "mhc-ticketing",
            "iat": 1_750_000_000,
            "exp": 1_750_000_300,
        }
    )

    assert user.keycloak_groups == ["ops-agents", "agent-it"]
    assert user._groups == ["ops-agents", "agent-it"]
    # Realm roles still drive the domains; the office claim confines them.
    assert get_user_scopes(user) == [
        Scope(domain="operational", office_id=str(office.id)),
        Scope(domain="it", office_id=str(office.id)),
    ]


@pytest.mark.parametrize(
    "role_key",
    [
        "records-officer",
        "examiner",
        "assistant-master",
        "deputy-master",
        "master",
    ],
)
def test_verified_token_retains_internal_staff_realm_roles(role_key):
    user, _ = _authenticate_verified_payload(
        {
            "sub": f"{role_key}-subject",
            "preferred_username": f"{role_key}-user",
            "realm_access": {"roles": [role_key, "offline_access"]},
            "iss": "https://idp.example.test/realms/mhc",
            "aud": "mhc-ticketing",
            "iat": 1_750_000_000,
            "exp": 1_750_000_300,
        }
    )

    assert user.keycloak_groups == [role_key]
    assert user._groups == [role_key]
    # A token designation is identity context only; scoped UserRole records
    # remain the source of operational authority.
    assert get_user_scopes(user) == []


def test_nested_keycloak_group_path_cannot_grant_a_privileged_realm_role():
    user, _ = _authenticate_verified_payload(
        {
            "sub": "nested-group-subject",
            "preferred_username": "nested-group-user",
            "email": "nested-group-user@example.test",
            "groups": ["/department/admin", "/project/auditor"],
            "realm_access": {"roles": ["staff"]},
            "acr": "mfa",
            "iss": "https://idp.example.test/realms/mhc",
            "aud": "mhc-ticketing",
            "iat": 1_750_000_000,
            "exp": 1_750_000_300,
        }
    )

    assert user.keycloak_groups == []
    assert user._groups == []
    assert get_user_scopes(user) == []
