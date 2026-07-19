"""Development profile: ``DJANGO_SETTINGS_MODULE=config.settings.dev``.

Use this on a developer machine or in the default ``docker-compose.yml``.
Includes the dev auth bypass, ``runserver``-style autoreload, and the
convenience defaults that hide real production warnings.
"""
from .base import *  # noqa: F401,F403

DEBUG = True
ENVIRONMENT = "development"

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])
CORS_ALLOWED_ORIGINS = env.list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)


def _patch_dev_auth():
    """Late-bind the dev-token shortcut. Done in a function so Django's app
    registry is fully ready before we touch the auth class.
    """
    from apps.identity_access.authentication import KeycloakJWTAuthentication

    def _authenticate(self, request):
        from django.conf import settings as _s
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.startswith("Bearer dev:") and _s.DEBUG:
            # Hand off to the base class — it already handles dev tokens.
            pass
        return KeycloakJWTAuthentication.authenticate(self, request)

    KeycloakJWTAuthentication.authenticate = _authenticate
