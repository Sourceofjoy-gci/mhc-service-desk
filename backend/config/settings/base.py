"""
Django settings for the MHC e-Ticketing backend.

Modules are read from environment variables via django-environ. The split
between base / dev / prod mirrors the deployment profile described in the PRD.
"""
from __future__ import annotations

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    ENVIRONMENT=(str, "development"),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", "backend"]),
    DJANGO_CORS_ALLOWED_ORIGINS=(list, ["http://localhost:5173"]),
)
env_file = BASE_DIR / ".." / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

# -----------------------------------------------------------------------------
# Core
# -----------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
ENVIRONMENT = env("ENVIRONMENT", default="development")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_prometheus",
    # Local apps — see PRD §25.2 module boundaries
    "apps.identity_access",
    "apps.organisations",
    "apps.contacts",
    "apps.catalogue",
    "apps.tickets",
    "apps.workflow",
    "apps.sla",
    "apps.files",
    "apps.audit",
    "apps.notifications",
    "apps.integrations",
    "apps.email_channel",
    "apps.whatsapp",
    "apps.knowledge",
    "apps.csat",
    "apps.automation",
    "apps.reporting",
    "apps.administration",
    "apps.health",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.audit.middleware.RequestAuditMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=(
            f"postgresql://{env('POSTGRES_USER', default='mhc')}:"
            f"{env('POSTGRES_PASSWORD', default='')}"
            f"@{env('POSTGRES_HOST', default='postgres')}:"
            f"{env('POSTGRES_PORT', default='5432')}"
            f"/{env('POSTGRES_DB', default='mhc')}"
        ),
    ),
}
DATABASES["default"].setdefault("ENGINE", "django_prometheus.db.backends.postgresql")
DATABASES["default"]["OPTIONS"] = {
    "connect_timeout": 5,
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------------------------------------------------------------
# Auth — staff via Keycloak OIDC; service tokens via JWT
# -----------------------------------------------------------------------------
AUTH_USER_MODEL = "identity_access.User"

AUTHENTICATION_BACKENDS = [
    "apps.identity_access.auth_backends.KeycloakOIDCBackend",
    "django.contrib.auth.backends.ModelBackend",
]

KEYCLOAK = {
    "BASE_URL": env("KEYCLOAK_BASE_URL", default="http://keycloak:8080"),
    "PUBLIC_URL": env("KEYCLOAK_PUBLIC_URL", default="http://localhost:8080"),
    "REALM": env("KEYCLOAK_REALM", default="mhc"),
    "CLIENT_ID": env("KEYCLOAK_CLIENT_ID", default="mhc-frontend"),
    "CLIENT_SECRET": env("KEYCLOAK_CLIENT_SECRET", default=""),
    "AUDIENCE": env("KEYCLOAK_CLIENT_ID_BACKEND", default="mhc-backend"),
    "VERIFICATION_KEYS_URL": env(
        "KEYCLOAK_VERIFICATION_KEYS_URL",
        default=f"{env('KEYCLOAK_BASE_URL', default='http://keycloak:8080')}"
                f"/realms/{env('KEYCLOAK_REALM', default='mhc')}/protocol/openid-connect/certs",
    ),
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.identity_access.authentication.KeycloakJWTAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "EXCEPTION_HANDLER": "apps.identity_access.exception_handlers.problem_details_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.identity_access.pagination.SafeCursorPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "600/minute",
        "anon": "60/minute",
        "public_intake": "5/minute",  # per-IP web form cap
    },
}

# -----------------------------------------------------------------------------
# CORS
# -----------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "x-csrftoken",
    "x-requested-with",
    "x-idempotency-key",
]

# -----------------------------------------------------------------------------
# Internationalisation — Eswatini timezone, English
# -----------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Mbabane"
USE_I18N = True
USE_TZ = True

# -----------------------------------------------------------------------------
# Static / media
# -----------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS: list[Path] = []

# Media uploads are delegated to MinIO via django-storages
# Two URLs: the *public* URL is what browsers hit; the *internal* URL is what
# the backend uses inside the Docker network so we don't hop through the host.
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
AWS_STORAGE_BUCKET_NAME = env("MINIO_BUCKET", default="mhc-attachments")
AWS_S3_ENDPOINT_URL = env("MINIO_INTERNAL_URL", default="http://minio:9000")
AWS_S3_PUBLIC_URL = env("MINIO_PUBLIC_URL", default="http://localhost:9000")
AWS_S3_ADDRESSING_STYLE = "path"
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_S3_REGION_NAME = "eswatini-1"
AWS_ACCESS_KEY_ID = env("MINIO_ROOT_USER", default="")
AWS_SECRET_ACCESS_KEY = env("MINIO_ROOT_PASSWORD", default="")
CLAMAV_HOST = env("CLAMAV_HOST", default="clamav")
CLAMAV_PORT = env.int("CLAMAV_PORT", default=3310)
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 60  # short-lived signed URLs (PRD FR-095)
AWS_DEFAULT_ACL = None

MEDIA_URL = f"{AWS_S3_PUBLIC_URL}/{AWS_STORAGE_BUCKET_NAME}/"
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024  # 25 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

# -----------------------------------------------------------------------------
# Security — production profile, relaxed in DEBUG
# -----------------------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Password validators (kept — Keycloak enforces real policy; this is a backstop
# for the local admin and any test users)
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -----------------------------------------------------------------------------
# Celery
# -----------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="amqp://mhc:change@rabbitmq:5672//")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://redis:6379/1")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_ROUTES = {
    "apps.notifications.tasks.*": {"queue": "notifications"},
    "apps.integrations.tasks.*": {"queue": "integrations"},
    "apps.sla.tasks.*": {"queue": "sla"},
    "apps.files.tasks.*": {"queue": "files"},
}
CELERY_BEAT_SCHEDULE = {
    "sla-evaluator": {
        "task": "apps.sla.tasks.evaluate_open_slas",
        "schedule": 60.0,  # every minute
    },
    "audit-export-cleanup": {
        "task": "apps.audit.tasks.rotate_export_artefacts",
        "schedule": 3600.0,  # hourly
    },
    "retention-side-effects": {
        "task": "apps.administration.tasks.process_retention_side_effects",
        "schedule": 60.0,
    },
}

# -----------------------------------------------------------------------------
# Logging — structured JSON, redacted
# -----------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "apps.audit.logging.JSONFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "celery": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "apps": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}

# -----------------------------------------------------------------------------
# Observability
# -----------------------------------------------------------------------------
OTEL_SERVICE_NAME = "mhc-backend"
OTEL_EXPORTER_OTLP_ENDPOINT = env("OTEL_EXPORTER_OTLP_ENDPOINT", default="")
# Prometheus metrics are exposed via the /metrics URL wired in config/urls.py
# by django_prometheus.urls. The standalone side-car port is intentionally not
# used so we don't need a second listener in the container.

# -----------------------------------------------------------------------------
# Domain configuration objects loaded from DB (placeholders, see apps.administration)
# -----------------------------------------------------------------------------
APP_CONFIG = {
    "BUSINESS_TIMEZONE": "Africa/Mbabane",
    "TICKET_NUMBER_FORMAT_OPERATIONAL": "OP-{YYYY}{MM}-{seq:06d}",
    "TICKET_NUMBER_FORMAT_IT": "IT-{YYYY}{MM}-{seq:06d}",
    "SLA_EVALUATION_INTERVAL_SECONDS": 60,
    "ATTACHMENT_QUARANTINE_PATH": "quarantine/",
    "AUDIT_LOG_RETENTION_DAYS": 2555,  # 7 years; pending records retention review
}
