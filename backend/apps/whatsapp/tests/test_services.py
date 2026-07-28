"""Provider boundary tests for the official WhatsApp Cloud API adapter."""
from __future__ import annotations

import requests
import responses

from apps.whatsapp.services import CloudProvider


@responses.activate
def test_cloud_provider_sends_approved_template_with_account_credentials() -> None:
    responses.post(
        "https://graph.facebook.com/v20.0/phone-123/messages",
        json={"messages": [{"id": "wamid.cloud"}]},
        status=200,
    )

    result = CloudProvider().send_template(
        to="+26876000001",
        template_name="case_update",
        language="en",
        parameters=["ready"],
        phone_number_id="phone-123",
        account_token="account-token",
    )

    assert result == {
        "status": "sent",
        "external_message_id": "wamid.cloud",
        "provider": "cloud",
    }
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer account-token"
    assert request.body == (
        b'{"messaging_product": "whatsapp", "to": "+26876000001", '
        b'"type": "template", "template": {"name": "case_update", '
        b'"language": {"code": "en"}, "components": [{"type": "body", '
        b'"parameters": [{"type": "text", "text": "ready"}]}]}}'
    )


@responses.activate
def test_cloud_provider_returns_failed_when_meta_is_unreachable() -> None:
    responses.post(
        "https://graph.facebook.com/v20.0/phone-123/messages",
        body=requests.Timeout("provider timeout with sensitive detail"),
    )

    result = CloudProvider().send_template(
        to="+26876000001",
        template_name="case_update",
        language="en",
        parameters=["ready"],
        phone_number_id="phone-123",
        account_token="account-token",
    )

    assert result == {"status": "failed", "error": "provider unavailable"}
