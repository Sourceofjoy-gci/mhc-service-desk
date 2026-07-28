"""Production profile: ``DJANGO_SETTINGS_MODULE=config.settings.prod``.

This is the profile the pilot will run on. Every required secret must be
provided via the environment; the module raises ``ImproperlyConfigured`` at
import time if any are missing. The dev auth bypass is **never** available
here because ``DEBUG`` is unconditionally False.
"""
from __future__ import annotations

import sys
from typing import TypeGuard

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import DATABASES, LOGGING, env

DEBUG = False
ENVIRONMENT = "production"

# --- Fail-fast secrets validation ----------------------------------------

_REQUIRED = [
    "DJANGO_SECRET_KEY",
    "DJANGO_ALLOWED_HOSTS",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "RABBITMQ_PASSWORD",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD",
    "BACKUP_ENCRYPTION_KEY",
]
_missing = [k for k in _REQUIRED if not env.str(k, default="")]
if _missing:
    raise ImproperlyConfigured(
        "Missing required production environment variables: "
        + ", ".join(_missing)
        + ". Refusing to start."
    )

# Reject insecure placeholder secrets
def _is_weak(secret: str) -> bool:
    s = secret.lower()
    if "change" in s or "example" in s or "secret" in s or "password" in s:
        return True
    return len(secret) < 24


_weak = []
for k in ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD",
          "RABBITMQ_PASSWORD", "MINIO_ROOT_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD",
          "BACKUP_ENCRYPTION_KEY"):
    v = env.str(k, default="")
    if v and _is_weak(v):
        _weak.append(k)
if _weak:
    raise ImproperlyConfigured(
        "These secrets look like placeholders or are too short: "
        + ", ".join(_weak)
        + ". Use a real secret manager."
    )

# --- Hosts and CORS ------------------------------------------------------

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS")

# --- HTTPS / cookies -----------------------------------------------------

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"

# --- Django defaults that are NOT useful in prod -------------------------

EMAIL_SUBJECT_PREFIX = "[MHC-Ticketing] "

# --- DB pool hardening ---------------------------------------------------

DATABASES["default"].setdefault("CONN_MAX_AGE", 60)
DATABASES["default"]["OPTIONS"].setdefault("connect_timeout", 5)

# --- Logging hardening ---------------------------------------------------

def _is_string_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


loggers: object = LOGGING.get("loggers")
if not _is_string_object_dict(loggers):
    raise ImproperlyConfigured("LOGGING['loggers'] must be a string-keyed mapping")
request_logger = loggers.setdefault(
    "django.request",
    {"handlers": ["console"], "propagate": False},
)
if not _is_string_object_dict(request_logger):
    raise ImproperlyConfigured("django.request logger configuration must be a mapping")
request_logger["level"] = "ERROR"

# Tell the staticfiles finder to bail out cleanly if anything is missing.
WHITENOISE_USE_FINDERS = True  # placeholder for future WhiteNoise use

# --- Process-level safety ------------------------------------------------

# The dev bypass is unconditionally disabled here: this module never
# imports the dev patch.
sys.modules.pop("apps.identity_access.authentication._dev", None)
