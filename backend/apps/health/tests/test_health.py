"""Smoke tests for the health endpoint."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_returns_status():
    client = APIClient()
    with patch("apps.health.views._check_db", return_value=(True, None)), \
         patch("apps.health.views._check_redis", return_value=(True, None)), \
         patch("apps.health.views._check_minio", return_value=(True, None)), \
         patch("apps.health.views._check_keycloak", return_value=(True, None)):
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "checks" in body
    for name in ("database", "redis", "minio", "keycloak"):
        assert name in body["checks"]
        assert body["checks"][name]["ok"] is True


def test_liveness_is_minimal():
    client = APIClient()
    resp = client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}
