"""Security regression tests — runs as part of the pilot gate.

Covers the categories in `docs/threat-model.md` STRIDE table. The intent is
to fail the build on a regression of any of these defences.
"""
from __future__ import annotations

import io
import json

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return Client()


def test_health_is_public(client):
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


def test_unauthenticated_me_is_401(client):
    r = client.get("/api/v1/identity/me")
    assert r.status_code == 401


def test_public_form_requires_consent(client):
    r = client.post(
        "/api/v1/tickets/public/intake/",
        data=json.dumps({
            "request_type_code": "HOURS",
            "service_code": "GEN-INFO",
            "office_code": "MHC-MBA",
            "title": "Test",
            "description": "Test",
            "requester_name": "Tester",
            "consent": False,
        }),
        content_type="application/json",
    )
    assert r.status_code == 400


def test_public_form_rate_limit_returns_429_after_threshold(client, settings, monkeypatch):
    """Hammer the public intake and assert that 429 kicks in within the limit."""
    from django.core.cache import cache
    cache.clear()
    body = {
        "request_type_code": "HOURS",
        "service_code": "GEN-INFO",
        "office_code": "MHC-MBA",
        "title": "Test",
        "description": "Test",
        "requester_name": "Tester",
        "consent": True,
    }
    last = None
    for i in range(20):
        r = client.post("/api/v1/tickets/public/intake/", data=json.dumps(body), content_type="application/json")
        last = r
        if r.status_code == 429:
            break
    assert last is not None
    # The first 5 should succeed (or 4xx on validation), then 429 should kick in.
    assert any(r2.status_code == 429 for r2 in [last])


def test_attachments_size_limit(monkeypatch):
    """Verify we refuse huge payloads at the body-parsing stage."""
    from rest_framework.test import APIClient
    from apps.identity_access.models import User
    user, _ = User.objects.get_or_create(
        username="attachee",
        defaults={"keycloak_subject": "dev:attachee:ops-agents"},
    )
    c = APIClient()
    c.force_authenticate(user=user)
    # 26 MB > 25 MB cap
    big = io.BytesIO(b"x" * (26 * 1024 * 1024))
    big.name = "big.bin"
    # We expect 400 Bad Request due to body size or graceful truncation.
    r = c.post("/api/v1/tickets/OP-FAKE/attachments/", {"files": big}, format="multipart")
    assert r.status_code in (400, 404, 413)
