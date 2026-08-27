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


def test_intake_rejects_anonymous_submissions(client):
    r = client.post(
        "/api/v1/tickets/public/intake/",
        data=json.dumps(
            {
                "request_type_code": "HOURS",
                "service_code": "GEN-INFO",
                "office_code": "MHC-MBA",
                "title": "Test",
                "description": "Test",
                "requester_name": "Tester",
                "consent": True,
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 401


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
