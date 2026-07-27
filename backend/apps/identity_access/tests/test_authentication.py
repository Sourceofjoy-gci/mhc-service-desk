from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from apps.identity_access.authentication import KeycloakJWTAuthentication

pytestmark = pytest.mark.django_db


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
