from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
STRONG_VALUE = "Aa7Bb8Cc9Dd0Ee1Ff2Gg3Hh4Ii5Jj6Kk"
REQUIRED_STRONG_VALUES = {
    "DJANGO_SECRET_KEY": STRONG_VALUE,
    "POSTGRES_PASSWORD": STRONG_VALUE,
    "REDIS_PASSWORD": STRONG_VALUE,
    "RABBITMQ_PASSWORD": STRONG_VALUE,
    "MINIO_ROOT_PASSWORD": STRONG_VALUE,
    "KEYCLOAK_ADMIN_PASSWORD": STRONG_VALUE,
    "BACKUP_ENCRYPTION_KEY": STRONG_VALUE,
}
PROBE = """
import json
import sys
from types import ModuleType

dev_auth_module = "apps.identity_access.authentication._dev"
sys.modules[dev_auth_module] = ModuleType(dev_auth_module)

try:
    from config.settings import prod
except Exception as exc:
    print(json.dumps({"error_type": type(exc).__name__, "message": str(exc)}))
    raise SystemExit(1)

print(json.dumps({
    "debug": prod.DEBUG,
    "environment": prod.ENVIRONMENT,
    "request_logger_level": prod.LOGGING["loggers"]["django.request"]["level"],
    "dev_auth_loaded": dev_auth_module in sys.modules,
    "conn_max_age": prod.DATABASES["default"].get("CONN_MAX_AGE"),
    "connect_timeout": prod.DATABASES["default"]["OPTIONS"].get("connect_timeout"),
}))
"""


async def _run_prod_probe_async(
    environment: dict[str, str],
) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        PROBE,
        cwd=BACKEND_ROOT,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return process.returncode, stdout.decode(), stderr.decode()


def _run_prod_probe(**overrides: str) -> tuple[int, str, str]:
    environment = os.environ.copy()
    environment.update(REQUIRED_STRONG_VALUES)
    environment.update(
        {
            "DJANGO_ALLOWED_HOSTS": "pilot.internal",
            "DJANGO_CORS_ALLOWED_ORIGINS": "https://pilot.internal",
            "MINIO_ROOT_USER": "pilot-storage",
            "DATABASE_URL": (f"postgresql://mhc:{STRONG_VALUE}@localhost:5432/mhc"),
            "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        }
    )
    environment.update(overrides)
    return asyncio.run(_run_prod_probe_async(environment))


def test_production_settings_import_with_strong_environment():
    returncode, output, errors = _run_prod_probe()

    assert returncode == 0, errors or output
    assert json.loads(output) == {
        "debug": False,
        "environment": "production",
        "request_logger_level": "ERROR",
        "dev_auth_loaded": False,
        "conn_max_age": 60,
        "connect_timeout": 5,
    }


def test_production_settings_fail_fast_when_required_value_is_missing():
    returncode, output, _ = _run_prod_probe(BACKUP_ENCRYPTION_KEY="")

    assert returncode == 1
    failure = json.loads(output)
    assert failure["error_type"] == "ImproperlyConfigured"
    assert "Missing required production environment variables" in failure["message"]
    assert "BACKUP_ENCRYPTION_KEY" in failure["message"]

def test_production_settings_fail_fast_when_required_secret_is_weak():
    returncode, output, _ = _run_prod_probe(BACKUP_ENCRYPTION_KEY="too-short")

    assert returncode == 1
    failure = json.loads(output)
    assert failure["error_type"] == "ImproperlyConfigured"
    assert "look like placeholders or are too short" in failure["message"]
    assert "BACKUP_ENCRYPTION_KEY" in failure["message"]
