"""Django auth backend shim that defers password authentication to the
local admin user only. Staff login happens through Keycloak OIDC.
"""

from __future__ import annotations

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import check_password
from django.http import HttpRequest

from .models import User


class KeycloakOIDCBackend(ModelBackend):
    """No password-based login for Keycloak-mirrored users."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: object,
    ) -> User | None:  # noqa: D401
        if username is None or password is None:
            return None
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return None
        if user.has_usable_password() and check_password(password, user.password):
            return user
        return None
