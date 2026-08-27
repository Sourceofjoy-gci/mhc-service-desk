"""Provider boundary tests for the official WhatsApp Cloud API adapter."""

from __future__ import annotations

import pytest
import requests
import responses

from apps.whatsapp.services import (
    CloudProvider,
    ProviderTemplateDiscoveryError,
)


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


@responses.activate
def test_cloud_template_discovery_preserves_an_honest_empty_catalog() -> None:
    responses.get(
        "https://graph.facebook.com/v20.0/business-123/message_templates",
        json={"data": []},
        status=200,
    )

    templates = CloudProvider().fetch_templates(
        account_token="account-token",
        business_id="business-123",
    )

    assert templates == []


@responses.activate
@pytest.mark.parametrize("provider_failure", ["timeout", "service_unavailable"])
def test_cloud_template_discovery_raises_sanitized_retryable_outage(
    provider_failure: str,
) -> None:
    if provider_failure == "timeout":
        responses.get(
            "https://graph.facebook.com/v20.0/business-123/message_templates",
            body=requests.Timeout("provider timeout with sensitive detail"),
        )
    else:
        responses.get(
            "https://graph.facebook.com/v20.0/business-123/message_templates",
            body="sensitive upstream failure",
            status=503,
        )

    with pytest.raises(ProviderTemplateDiscoveryError) as exc_info:
        CloudProvider().fetch_templates(
            account_token="account-token",
            business_id="business-123",
        )

    assert exc_info.value.retryable is True
    assert "sensitive" not in str(exc_info.value)
