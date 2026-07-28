"""Smoke tests for the health endpoint."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.health import views as health_views


@pytest.mark.django_db
def test_readiness_returns_ok_when_every_registered_check_passes():
    client = APIClient()
    original_checks = health_views.CHECKS.copy()
    passing_checks = {
        "database": lambda: (True, None),
        "redis": lambda: (True, None),
        "minio": lambda: (True, None),
        "keycloak": lambda: (True, None),
    }

    with patch.dict(health_views.CHECKS, passing_checks, clear=True):
        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == set(passing_checks)
    assert all(result["ok"] is True for result in body["checks"].values())
    assert health_views.CHECKS == original_checks


@pytest.mark.django_db
def test_readiness_reports_the_named_failed_check_without_leaking_registry_state():
    client = APIClient()
    original_checks = health_views.CHECKS.copy()
    failing_checks = {
        "database": lambda: (True, None),
        "redis": lambda: (False, "connection refused"),
    }

    with patch.dict(health_views.CHECKS, failing_checks, clear=True):
        resp = client.get("/api/v1/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["ok"] is True
    assert "error" not in body["checks"]["database"]
    assert body["checks"]["redis"]["ok"] is False
    assert body["checks"]["redis"]["error"] == "connection refused"
    assert health_views.CHECKS == original_checks


def test_liveness_is_minimal():
    client = APIClient()
    resp = client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}
