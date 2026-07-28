"""WhatsApp provider abstraction.

Two providers are wired:
  * `mock`     — accepts and acknowledges messages in-process; for dev/test.
  * `cloud`    — POSTs to the official Meta Cloud API. Reserved for
                  production use once the Meta account and templates are
                  approved (PRD §19.6).
"""
from __future__ import annotations

import logging
import os
from typing import TypedDict

import requests
from django.db import transaction

from apps.email_channel.services import process_inbound_email

logger = logging.getLogger(__name__)


class _CloudMessage(TypedDict, total=False):
    id: str


class _CloudSendResponse(TypedDict, total=False):
    messages: list[_CloudMessage]


class _CloudTemplatesResponse(TypedDict, total=False):
    data: list[dict[str, object]]


def get_provider(name: str | None = None) -> BaseProvider:
    name = (name or os.environ.get("WHATSAPP_PROVIDER") or "mock").lower()
    if name == "cloud":
        return CloudProvider()
    return MockProvider()


class BaseProvider:
    def send_text(
        self,
        *,
        to: str,
        body: str,
        account_token: str = "",
    ) -> dict[str, str]:
        raise NotImplementedError

    def fetch_templates(self) -> list[dict[str, object]]:
        raise NotImplementedError


class MockProvider(BaseProvider):
    """In-process provider. Records the call and returns a fake id."""

    def send_text(
        self,
        *,
        to: str,
        body: str,
        account_token: str = "",
    ) -> dict[str, str]:
        return {
            "status": "sent",
            "external_message_id": f"mock-{abs(hash((to, body))) % 10**10}",
            "provider": "mock",
        }

    def fetch_templates(self) -> list[dict[str, object]]:
        return [
            {"name": "ticket_ack_en", "language": "en", "category": "utility",
             "body": "Your request {{1}} has been received. Reference: {{2}}."},
            {"name": "ticket_ack_ss", "language": "ss", "category": "utility",
             "body": "Inchaziso yakho {{1}} itholakele. Inombolo: {{2}}."},
        ]


class CloudProvider(BaseProvider):
    """Real Meta Cloud API client.

    Not exercised in P0 dev. Documented here so the wiring is in place when
    the Meta account is approved.
    """

    BASE = "https://graph.facebook.com/v20.0"

    def send_text(
        self,
        *,
        to: str,
        body: str,
        account_token: str = "",
    ) -> dict[str, str]:
        if not account_token:
            return {"status": "failed", "error": "missing access token"}
        r = requests.post(
            f"{self.BASE}/{os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '')}/messages",
            headers={"Authorization": f"Bearer {account_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body},
            },
            timeout=5,
        )
        if r.ok:
            data: _CloudSendResponse = r.json()
            return {
                "status": "sent",
                "external_message_id": data.get("messages", [{}])[0].get("id", ""),
                "provider": "cloud",
            }
        return {"status": "failed", "error": r.text[:300]}

    def fetch_templates(self) -> list[dict[str, object]]:
        if not os.environ.get("WHATSAPP_ACCESS_TOKEN"):
            return []
        r = requests.get(
            f"{self.BASE}/{os.environ.get('WHATSAPP_BUSINESS_ID', '')}/message_templates",
            headers={"Authorization": f"Bearer {os.environ.get('WHATSAPP_ACCESS_TOKEN')}"},
            timeout=5,
        )
        if not r.ok:
            return []
        data: _CloudTemplatesResponse = r.json()
        return data.get("data", [])


# --- Inbound webhook processing -------------------------------------------


@transaction.atomic
def process_inbound_whatsapp(
    *,
    from_number: str,
    to_number: str,
    body: str,
    external_message_id: str = "",
    raw: dict[str, object] | None = None,
) -> dict[str, str]:
    """Reuse the email channel's idempotency / threading / sanitisation path
    by treating the WhatsApp message as an email from the same person.

    Meta requires approved templates for outbound; inbound is always plain
    text. We attribute the message to the contact by phone number.
    """
    from apps.contacts.models import Contact
    from .models import WhatsappMessage

    # Prevent duplicate delivery using provider id
    if (
        external_message_id
        and WhatsappMessage.objects.filter(
            external_message_id=external_message_id
        ).exists()
    ):
        return {"status": "duplicate"}

    contact, _ = Contact.objects.get_or_create(
        phone_e164=from_number,
        defaults={"full_name": f"WhatsApp {from_number[-4:]}"},
    )

    # Use a synthetic email to reuse the email intake pipeline
    outcome = process_inbound_email(
        from_header=contact.full_name,
        to_header=to_number,
        subject="WhatsApp enquiry",
        body_text=body,
        message_id=external_message_id or f"<wa:{from_number}:{hash(body)}@mhc>",
    )
    WhatsappMessage.objects.create(
        account=None,
        from_number=from_number,
        to_number=to_number,
        direction="inbound",
        body=body,
        external_message_id=external_message_id,
        raw_payload=raw or {},
    )
    return outcome
