from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from rest_framework.test import APIClient

from apps.identity_access.models import User


@dataclass
class StubProvider:
    templates: list[dict[str, str]] = field(
        default_factory=lambda: [{"name": "case_update", "status": "APPROVED"}]
    )
    fetch_count: int = 0
    sent: list[dict[str, str]] = field(default_factory=list)

    def fetch_templates(self):
        self.fetch_count += 1
        return self.templates

    def send_text(self, *, to: str, body: str):
        self.sent.append({"to": to, "body": body})
        return {"status": "sent", "provider_id": "wamid.test"}


def _authenticated_client(username: str, groups: str) -> APIClient:
    group_list = groups.split(",") if groups else []
    user = User.objects.create(
        username=username,
        keycloak_subject=f"test:{username}",
        keycloak_groups=group_list,
    )
    user._groups = group_list
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/integrations/whatsapp/templates/", None),
        (
            "post",
            "/api/v1/integrations/whatsapp/send/",
            {"to": "+27110000000", "body": "A safe update"},
        ),
    ],
)
def test_outbound_helpers_reject_anonymous_requests_before_calling_provider(
    monkeypatch,
    method,
    path,
    payload,
):
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = getattr(APIClient(), method)(path, payload, format="json")

    assert response.status_code == 401
    assert provider.fetch_count == 0
    assert provider.sent == []


@pytest.mark.django_db
def test_authenticated_staff_can_list_provider_templates(monkeypatch):
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("whatsapp-template-agent", "ops-agents").get(
        "/api/v1/integrations/whatsapp/templates/"
    )

    assert response.status_code == 200
    assert response.json() == {"templates": provider.templates}
    assert provider.fetch_count == 1


@pytest.mark.django_db
def test_authenticated_non_auditor_can_send_text(monkeypatch):
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)
    payload = {"to": "+27110000000", "body": "A safe update"}

    response = _authenticated_client("whatsapp-send-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        payload,
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "sent", "provider_id": "wamid.test"}
    assert provider.sent == [payload]


@pytest.mark.django_db
def test_auditor_cannot_send_text_or_call_provider(monkeypatch):
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("whatsapp-auditor", "auditors").post(
        "/api/v1/integrations/whatsapp/send/",
        {"to": "+27110000000", "body": "A safe update"},
        format="json",
    )

    assert response.status_code == 403
    assert provider.sent == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"to": "", "body": "A safe update"},
        {"to": "+27110000000", "body": ""},
    ],
)
def test_send_validation_rejects_incomplete_payload_before_calling_provider(
    monkeypatch,
    payload,
):
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("whatsapp-validation-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "to and body are required"}
    assert provider.sent == []
