"""WhatsApp provider abstraction.

Two providers are wired:
  * `mock`     — accepts and acknowledges messages in-process; for dev/test.
  * `cloud`    — POSTs to the official Meta Cloud API. Reserved for
                  production use once the Meta account and templates are
                  approved (PRD §19.6).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import TYPE_CHECKING, TypedDict

import requests
from django.db import IntegrityError, transaction

from apps.email_channel.services import process_inbound_email
from apps.tickets.models import Ticket

if TYPE_CHECKING:
    from .models import WhatsappAccount

logger = logging.getLogger(__name__)


class _CloudMessage(TypedDict, total=False):
    id: str


class _CloudSendResponse(TypedDict, total=False):
    messages: list[_CloudMessage]


class _CloudTemplatesResponse(TypedDict, total=False):
    data: list[dict[str, object]]


class ProviderTemplateDiscoveryError(RuntimeError):
    """Sanitized provider failure that preserves whether retry is appropriate."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__("WhatsApp template discovery is unavailable")
        self.retryable = retryable


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

    def send_template(
        self,
        *,
        to: str,
        template_name: str,
        language: str,
        parameters: list[str],
        phone_number_id: str,
        account_token: str,
    ) -> dict[str, str]:
        raise NotImplementedError

    def fetch_templates(
        self,
        *,
        account_token: str = "",
        business_id: str = "",
    ) -> list[dict[str, object]]:
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

    def send_template(
        self,
        *,
        to: str,
        template_name: str,
        language: str,
        parameters: list[str],
        phone_number_id: str,
        account_token: str,
    ) -> dict[str, str]:
        digest = hashlib.sha256(
            f"{phone_number_id}|{to}|{template_name}|{language}|{parameters}".encode()
        ).hexdigest()[:20]
        return {
            "status": "sent",
            "external_message_id": f"mock-{digest}",
            "provider": "mock",
        }

    def fetch_templates(
        self,
        *,
        account_token: str = "",
        business_id: str = "",
    ) -> list[dict[str, object]]:
        return [
            {
                "name": "ticket_ack_en",
                "language": "en",
                "category": "utility",
                "status": "APPROVED",
                "body": "Your request {{1}} has been received. Reference: {{2}}.",
            },
            {
                "name": "ticket_ack_ss",
                "language": "ss",
                "category": "utility",
                "status": "APPROVED",
                "body": "Inchaziso yakho {{1}} itholakele. Inombolo: {{2}}.",
            },
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
        try:
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
        except requests.RequestException:
            return {"status": "failed", "error": "provider unavailable"}
        if r.ok:
            data: _CloudSendResponse = r.json()
            return {
                "status": "sent",
                "external_message_id": data.get("messages", [{}])[0].get("id", ""),
                "provider": "cloud",
            }
        return {"status": "failed", "error": r.text[:300]}

    def send_template(
        self,
        *,
        to: str,
        template_name: str,
        language: str,
        parameters: list[str],
        phone_number_id: str,
        account_token: str,
    ) -> dict[str, str]:
        if not account_token or not phone_number_id:
            return {"status": "failed", "error": "missing account configuration"}
        components: list[dict[str, object]] = []
        if parameters:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": parameter} for parameter in parameters],
                }
            )
        try:
            response = requests.post(
                f"{self.BASE}/{phone_number_id}/messages",
                headers={"Authorization": f"Bearer {account_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {"code": language},
                        "components": components,
                    },
                },
                timeout=5,
            )
        except requests.RequestException:
            return {"status": "failed", "error": "provider unavailable"}
        if response.ok:
            data: _CloudSendResponse = response.json()
            return {
                "status": "sent",
                "external_message_id": data.get("messages", [{}])[0].get("id", ""),
                "provider": "cloud",
            }
        return {"status": "failed", "error": response.text[:300]}

    def fetch_templates(
        self,
        *,
        account_token: str = "",
        business_id: str = "",
    ) -> list[dict[str, object]]:
        if not account_token or not business_id:
            raise ProviderTemplateDiscoveryError(retryable=False)
        try:
            r = requests.get(
                f"{self.BASE}/{business_id}/message_templates",
                headers={"Authorization": f"Bearer {account_token}"},
                timeout=5,
            )
        except requests.RequestException:
            raise ProviderTemplateDiscoveryError(retryable=True) from None
        if not r.ok:
            raise ProviderTemplateDiscoveryError(
                retryable=r.status_code == 429 or r.status_code >= 500,
            )
        try:
            data: _CloudTemplatesResponse = r.json()
        except ValueError:
            raise ProviderTemplateDiscoveryError(retryable=True) from None
        templates = data.get("data") if isinstance(data, dict) else None
        if not isinstance(templates, list) or not all(
            isinstance(template, dict) for template in templates
        ):
            raise ProviderTemplateDiscoveryError(retryable=True)
        return templates


# --- Inbound webhook processing -------------------------------------------


@transaction.atomic
def process_inbound_whatsapp(
    *,
    account: WhatsappAccount,
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

    try:
        with transaction.atomic():
            channel_message = WhatsappMessage.objects.create(
                account=account,
                from_number=from_number,
                to_number=to_number,
                direction=WhatsappMessage.Direction.INBOUND,
                body=body,
                external_message_id=external_message_id,
                delivery_status="received",
                raw_payload=raw or {},
            )
    except IntegrityError:
        return {"status": "duplicate"}

    contact, _ = Contact.objects.get_or_create(
        phone_e164=from_number,
        defaults={"full_name": f"WhatsApp {from_number[-4:]}"},
    )

    # Use a synthetic email to reuse the email intake pipeline
    outcome = process_inbound_email(
        from_header=from_number,
        to_header=to_number,
        subject="WhatsApp enquiry",
        body_text=body,
        message_id=external_message_id or f"<wa:{from_number}:{hash(body)}@mhc>",
        contact_override=contact,
        domain_override=account.domain,
        channel="whatsapp",
        source_account=account.phone_number_id,
        author_subject=from_number,
        author_label=contact.full_name,
        sender_verified=True,
    )
    if outcome.get("status") == "error":
        transaction.set_rollback(True)
        return outcome
    ticket_number = outcome.get("ticket_number")
    if ticket_number:
        channel_message.ticket = Ticket.objects.get(number=ticket_number)
        channel_message.save(update_fields=["ticket"])
    return outcome
