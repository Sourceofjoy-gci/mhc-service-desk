"""Health checks for the MHC e-Ticketing platform.

Exposes two endpoints:

* ``/api/v1/health`` — public liveness + readiness with dependency checks
* ``/api/v1/health/live`` — minimal liveness for k8s-style probes
"""
from __future__ import annotations

import socket
import time
from typing import Callable, NotRequired, TypedDict

import redis
from django.conf import settings
from django.db import connections
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request

from apps.identity_access.scope import public_endpoint  # noqa: F401  (used for type hint)


def _check_db() -> tuple[bool, str | None]:
    try:
        with connections["default"].cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True, None
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


def _check_redis() -> tuple[bool, str | None]:
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        client.ping()
        return True, None
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


def _check_minio() -> tuple[bool, str | None]:
    """Best-effort TCP check to MinIO. Auth is exercised separately when needed."""
    from urllib.parse import urlparse
    try:
        url = urlparse(settings.AWS_S3_ENDPOINT_URL)
        host = url.hostname or "minio"
        port = url.port or 9000
        with socket.create_connection((host, port), timeout=2):
            return True, None
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


def _check_keycloak() -> tuple[bool, str | None]:
    """Keycloak reachability check.

    In dev mode, ``/health`` is not exposed by default. We use the realm info
    endpoint (``/realms/<realm>``) which is always available when Keycloak is
    running and returns 200 with the realm metadata.
    """
    import requests
    try:
        r = requests.get(
            f"{settings.KEYCLOAK['BASE_URL']}/realms/{settings.KEYCLOAK['REALM']}",
            timeout=2,
        )
        return r.ok, None if r.ok else f"HTTP {r.status_code}"
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


CHECKS: dict[str, Callable[[], tuple[bool, str | None]]] = {
    "database": _check_db,
    "redis": _check_redis,
    "minio": _check_minio,
    "keycloak": _check_keycloak,
}


class HealthCheckResult(TypedDict):
    ok: bool
    latency_ms: float
    error: NotRequired[str]


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request: Request) -> JsonResponse:
    results: dict[str, HealthCheckResult] = {}
    overall_ok = True
    started = time.perf_counter()
    for name, fn in CHECKS.items():
        t0 = time.perf_counter()
        ok, err = fn()
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        results[name] = {"ok": ok, "latency_ms": elapsed_ms}
        if err:
            results[name]["error"] = err
        overall_ok = overall_ok and ok
    payload = {
        "status": "ok" if overall_ok else "degraded",
        "environment": settings.ENVIRONMENT,
        "version": "0.1.0",
        "checks": results,
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    return JsonResponse(payload, status=200 if overall_ok else 503)


@api_view(["GET"])
@permission_classes([AllowAny])
def liveness(_request: Request) -> JsonResponse:
    return JsonResponse({"status": "alive"})
