"""Staging profile: ``DJANGO_SETTINGS_MODULE=config.settings.staging``.

Mirrors the production runtime as closely as possible (DEBUG=False,
HTTPS-only cookies, gunicorn) but uses the same dev Keycloak realm and
allows the dev-bypass for smoke tests. Useful for QA and the pilot UAT.
"""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
ENVIRONMENT = "staging"

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["staging.mhc-ticketing.local", "api.staging.mhc-ticketing.local"],
)
CORS_ALLOWED_ORIGINS = env.list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    default=["https://staging.mhc-ticketing.local"],
)

# In staging we run over HTTPS in front of Nginx.
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Allow the dev auth bypass *only* in staging by setting DEBUG explicitly
# (the bypass checks the global DEBUG flag).
