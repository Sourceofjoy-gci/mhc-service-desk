"""Development profile: ``DJANGO_SETTINGS_MODULE=config.settings.dev``.

Use this on a developer machine or in the default ``docker-compose.yml``.
Includes the dev auth bypass, ``runserver``-style autoreload, and the
convenience defaults that hide real production warnings.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True
ENVIRONMENT = "development"

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])
CORS_ALLOWED_ORIGINS = env.list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)


def _patch_dev_auth() -> None:
    """Late-bind the dev-token shortcut. Done in a function so Django's app
    registry is fully ready before we touch the auth class.
    """
    from rest_framework.request import Request

    from apps.identity_access.authentication import KeycloakJWTAuthentication

    original_authenticate = KeycloakJWTAuthentication.authenticate

    def _authenticate(
        self: KeycloakJWTAuthentication,
        request: Request,
    ) -> tuple[object, object] | None:
        # The base class already enforces DEBUG for dev tokens.
        return original_authenticate(self, request)

    type.__setattr__(KeycloakJWTAuthentication, "authenticate", _authenticate)
