"""Authorization, authenticity and persistence tests for WhatsApp endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.contacts.models import Contact
from apps.identity_access.models import User
from apps.organisations.models import Office
from apps.tickets.models import OutboxEvent, Ticket, TicketMessage
from apps.whatsapp.models import WhatsappAccount, WhatsappMessage
from apps.whatsapp.services import ProviderTemplateDiscoveryError
from apps.workflow.models import Status

META_APP_SECRET = "meta-app-secret-for-tests"


@dataclass
class StubProvider:
    templates: list[dict[str, object]] = field(
        default_factory=lambda: [
            {
                "name": "case_update",
                "language": "en",
                "category": "UTILITY",
                "status": "APPROVED",
                "body": "Your case update is {{1}}.",
            }
        ]
    )
    fetch_count: int = 0
    fetched: list[dict[str, str]] = field(default_factory=list)
    sent: list[dict[str, object]] = field(default_factory=list)

    def fetch_templates(
        self,
        *,
        account_token: str = "",
        business_id: str = "",
    ) -> list[dict[str, object]]:
        self.fetch_count += 1
        self.fetched.append({"account_token": account_token, "business_id": business_id})
        return self.templates

    def send_text(self, *, to: str, body: str) -> dict[str, str]:
        self.sent.append({"legacy_to": to, "legacy_body": body})
        return {"status": "sent", "external_message_id": "wamid.legacy"}

    def send_template(self, **kwargs: object) -> dict[str, str]:
        self.sent.append(kwargs)
        return {
            "status": "sent",
            "external_message_id": "wamid.template-test",
            "provider": "cloud",
        }


def _authenticated_client(username: str, groups: str) -> APIClient:
    group_list = groups.split(",") if groups else []
    # Operational and IT authority is confined to the officer's office, so
    # every staff actor is based at the seeded ``basic_world`` office.
    user = User.objects.create(
        username=username,
        keycloak_subject=f"test:{username}",
        keycloak_groups=group_list,
        office=Office.objects.get(code="TST-1"),
    )
    user._groups = group_list
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _ticket(
    basic_world: dict[str, Any],
    *,
    domain: str = "operational",
    consent: bool = True,
    opted_out: bool = False,
) -> Ticket:
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    requester = Contact.objects.create(
        full_name=f"WhatsApp Requester {uuid4().hex}",
        phone_e164=f"+2687{uuid4().int % 10_000_000:07d}",
        consent_at=timezone.now() if consent else None,
        opted_out_at=timezone.now() if opted_out else None,
    )
    return Ticket.objects.create(
        number=f"{domain[:2].upper()}-202607-{Ticket.objects.count() + 970001:06d}",
        domain=domain,
        title="WhatsApp trust boundary",
        status=Status.objects.get(domain=domain, code="in_progress"),
        channel="web",
        requester=requester,
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _account(
    *,
    domain: str = "operational",
    active: bool = True,
    access_token: str | None = None,
    business_id: str | None = None,
) -> WhatsappAccount:
    return WhatsappAccount.objects.create(
        phone_number_id=f"phone-{uuid4().hex}",
        display_name=f"{domain} account",
        domain=domain,
        is_active=active,
        access_token=uuid4().hex if access_token is None else access_token,
        business_id=f"business-{uuid4().hex}" if business_id is None else business_id,
    )


def _meta_raw(
    account: WhatsappAccount,
    *,
    message_id: str,
    body: str = "Please help",
    issued_at: int | None = None,
) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": account.business_id,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {
                                "display_phone_number": "+26824000000",
                                "phone_number_id": account.phone_number_id,
                            },
                            "messages": [
                                {
                                    "from": "+26876000001",
                                    "id": message_id,
                                    "timestamp": str(
                                        issued_at if issued_at is not None else int(time.time())
                                    ),
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _meta_signature(raw_body: bytes, *, secret: str = META_APP_SECRET) -> str:
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _meta_status_raw(
    account: WhatsappAccount,
    *,
    message_id: str,
    delivery_status: str,
    issued_at: int | None = None,
) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": account.business_id,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {
                                "display_phone_number": "+26824000000",
                                "phone_number_id": account.phone_number_id,
                            },
                            "statuses": [
                                {
                                    "id": message_id,
                                    "status": delivery_status,
                                    "timestamp": str(
                                        issued_at if issued_at is not None else int(time.time())
                                    ),
                                    "recipient_id": "+26876000001",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode()


@pytest.fixture(autouse=True)
def _channel_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSAPP_APP_SECRET", META_APP_SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("WHATSAPP_BUSINESS_ID", "wrong-global-business-id")
    monkeypatch.setenv("CHANNEL_WEBHOOK_MAX_AGE_SECONDS", "300")


@pytest.mark.django_db
def test_meta_webhook_fails_closed_without_app_secret(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _account()
    raw_body = _meta_raw(account, message_id="wamid.no-secret")
    monkeypatch.delenv("WHATSAPP_APP_SECRET")

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
    )

    assert response.status_code == 503
    assert WhatsappMessage.objects.count() == 0
    assert Ticket.objects.count() == 0


@pytest.mark.django_db
def test_meta_webhook_rejects_invalid_signature_before_mutation(
    basic_world: dict[str, Any],
) -> None:
    account = _account()
    raw_body = _meta_raw(account, message_id="wamid.invalid-signature")

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=" + "0" * 64,
    )

    assert response.status_code == 401
    assert WhatsappMessage.objects.count() == 0
    assert Ticket.objects.count() == 0


@pytest.mark.django_db
def test_meta_webhook_rejects_stale_signed_message_before_mutation(
    basic_world: dict[str, Any],
) -> None:
    account = _account()
    raw_body = _meta_raw(
        account,
        message_id="wamid.stale",
        issued_at=int(time.time()) - 301,
    )

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
    )

    assert response.status_code == 401
    assert WhatsappMessage.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "malformation",
    [
        "wrong_object",
        "entry_not_list",
        "empty_entry",
        "changes_not_list",
        "empty_changes",
        "wrong_change_field",
        "empty_change_events",
    ],
)
def test_meta_webhook_rejects_malformed_envelope_before_mutation(
    basic_world: dict[str, Any],
    malformation: str,
) -> None:
    account = _account()
    payload = json.loads(_meta_raw(account, message_id="wamid.malformed"))
    entry = payload["entry"][0]
    change = entry["changes"][0]
    if malformation == "wrong_object":
        payload["object"] = "page"
    elif malformation == "entry_not_list":
        payload["entry"] = {}
    elif malformation == "empty_entry":
        payload["entry"] = []
    elif malformation == "changes_not_list":
        entry["changes"] = {}
    elif malformation == "empty_changes":
        entry["changes"] = []
    elif malformation == "wrong_change_field":
        change["field"] = "account_update"
    else:
        change["value"].pop("messages")
    raw_body = json.dumps(payload, separators=(",", ":")).encode()

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
    )

    assert response.status_code == 400
    assert response.json() == {"status": "invalid_payload"}
    assert WhatsappMessage.objects.count() == 0
    assert TicketMessage.objects.count() == 0


@pytest.mark.django_db
def test_meta_webhook_requires_waba_and_phone_number_to_match_same_account(
    basic_world: dict[str, Any],
) -> None:
    account = _account()
    other_account = _account()
    payload = json.loads(_meta_raw(account, message_id="wamid.waba-mismatch"))
    payload["entry"][0]["id"] = other_account.business_id
    raw_body = json.dumps(payload, separators=(",", ":")).encode()

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
    )

    assert response.status_code == 503
    assert response.json() == {"status": "account_unavailable"}
    assert WhatsappMessage.objects.count() == 0
    assert TicketMessage.objects.count() == 0


@pytest.mark.django_db
def test_meta_webhook_prevalidates_entire_batch_before_mutation(
    basic_world: dict[str, Any],
) -> None:
    account = _account()
    payload = json.loads(_meta_raw(account, message_id="wamid.valid-first"))
    payload["entry"].append(
        {
            "id": account.business_id,
            "changes": [{"field": "not_messages", "value": {}}],
        }
    )
    raw_body = json.dumps(payload, separators=(",", ":")).encode()

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
    )

    assert response.status_code == 400
    assert WhatsappMessage.objects.count() == 0
    assert TicketMessage.objects.count() == 0


@pytest.mark.django_db
def test_valid_meta_webhook_uses_configured_account_contact_and_domain(
    basic_world: dict[str, Any],
) -> None:
    account = _account(domain="it")
    raw_body = _meta_raw(account, message_id="wamid.valid")

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
    )

    assert response.status_code == 201
    ticket = Ticket.objects.get(number=response.json()["ticket_number"])
    message = WhatsappMessage.objects.get(external_message_id="wamid.valid")
    assert ticket.domain == "it"
    assert ticket.channel == "whatsapp"
    assert ticket.requester.phone_e164 == "+26876000001"
    assert message.account == account
    assert message.ticket == ticket
    assert message.raw_payload == {
        "provider_message_id": "wamid.valid",
        "type": "text",
    }


@pytest.mark.django_db
def test_meta_webhook_processes_every_message_in_a_signed_batch(
    basic_world: dict[str, Any],
) -> None:
    account = _account()
    payload = json.loads(_meta_raw(account, message_id="wamid.batch-one"))
    messages = payload["entry"][0]["changes"][0]["value"]["messages"]
    messages.append(
        {
            **messages[0],
            "id": "wamid.batch-two",
            "text": {"body": "A second request"},
        }
    )
    raw_body = json.dumps(payload, separators=(",", ":")).encode()

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
    )

    assert response.status_code == 201
    assert set(WhatsappMessage.objects.values_list("external_message_id", flat=True)) == {
        "wamid.batch-one",
        "wamid.batch-two",
    }
    assert TicketMessage.objects.filter(direction="inbound").count() == 2


@pytest.mark.django_db
def test_meta_delivery_status_is_account_bound_idempotent_and_audited(
    basic_world: dict[str, Any],
) -> None:
    ticket = _ticket(basic_world)
    account = _account()
    ticket_message = TicketMessage.objects.create(
        ticket=ticket,
        direction=TicketMessage.Direction.OUTBOUND,
        body_text="Template body",
        external_message_id="wamid.delivery",
        delivery_status="sent",
    )
    channel_message = WhatsappMessage.objects.create(
        ticket=ticket,
        account=account,
        direction=WhatsappMessage.Direction.OUTBOUND,
        body="Template body",
        external_message_id="wamid.delivery",
        delivery_status="sent",
    )
    raw_body = _meta_status_raw(
        account,
        message_id="wamid.delivery",
        delivery_status="delivered",
    )
    client = APIClient()
    headers = {"HTTP_X_HUB_SIGNATURE_256": _meta_signature(raw_body)}

    wrong_account = _account()
    wrong_body = _meta_status_raw(
        wrong_account,
        message_id="wamid.delivery",
        delivery_status="delivered",
    )
    wrong_account_response = client.generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        wrong_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(wrong_body),
    )
    channel_message.refresh_from_db()
    assert wrong_account_response.status_code == 503
    assert wrong_account_response.json()["status"] == "retry"
    assert channel_message.delivery_status == "sent"

    accepted = client.generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        **headers,
    )
    replayed = client.generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        **headers,
    )

    assert accepted.status_code == 200
    assert replayed.status_code == 200
    channel_message.refresh_from_db()
    ticket_message.refresh_from_db()
    assert channel_message.delivery_status == "delivered"
    assert ticket_message.delivery_status == "delivered"
    assert (
        AuditEvent.objects.filter(
            object_id=str(ticket.id),
            action="ticket.message.delivery_updated",
        ).count()
        == 1
    )
    assert (
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id),
            event_type="ticket.message.delivery_updated",
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_meta_statuses_use_rank_to_order_events_with_same_timestamp(
    basic_world: dict[str, Any],
) -> None:
    ticket = _ticket(basic_world)
    account = _account()
    issued_at = int(time.time())
    ticket_message = TicketMessage.objects.create(
        ticket=ticket,
        direction=TicketMessage.Direction.OUTBOUND,
        body_text="Template body",
        external_message_id="wamid.same-second",
        delivery_status="sent",
    )
    channel_message = WhatsappMessage.objects.create(
        ticket=ticket,
        account=account,
        direction=WhatsappMessage.Direction.OUTBOUND,
        body="Template body",
        external_message_id="wamid.same-second",
        delivery_status="sent",
        raw_payload={"status_timestamp": issued_at},
    )
    client = APIClient()

    for delivery_status in ("delivered", "read"):
        raw_body = _meta_status_raw(
            account,
            message_id="wamid.same-second",
            delivery_status=delivery_status,
            issued_at=issued_at,
        )
        response = client.generic(
            "POST",
            "/api/v1/integrations/whatsapp/webhook/",
            raw_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
        )
        assert response.status_code == 200

    channel_message.refresh_from_db()
    ticket_message.refresh_from_db()
    assert channel_message.delivery_status == "read"
    assert ticket_message.delivery_status == "read"
    assert (
        AuditEvent.objects.filter(
            object_id=str(ticket.id),
            action="ticket.message.delivery_updated",
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_meta_newer_same_status_advances_watermark_without_duplicate_event(
    basic_world: dict[str, Any],
) -> None:
    ticket = _ticket(basic_world)
    account = _account()
    prior_timestamp = int(time.time()) - 10
    channel_message = WhatsappMessage.objects.create(
        ticket=ticket,
        account=account,
        direction=WhatsappMessage.Direction.OUTBOUND,
        body="Template body",
        external_message_id="wamid.watermark",
        delivery_status="delivered",
        raw_payload={"status_timestamp": prior_timestamp},
    )
    newer_timestamp = prior_timestamp + 5
    raw_body = _meta_status_raw(
        account,
        message_id="wamid.watermark",
        delivery_status="delivered",
        issued_at=newer_timestamp,
    )

    response = APIClient().generic(
        "POST",
        "/api/v1/integrations/whatsapp/webhook/",
        raw_body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "timestamp_advanced"
    channel_message.refresh_from_db()
    assert channel_message.raw_payload["status_timestamp"] == newer_timestamp
    assert (
        AuditEvent.objects.filter(
            object_id=str(ticket.id),
            action="ticket.message.delivery_updated",
        ).count()
        == 0
    )
    assert (
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id),
            event_type="ticket.message.delivery_updated",
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_meta_status_never_regresses_or_accepts_an_older_higher_rank(
    basic_world: dict[str, Any],
) -> None:
    ticket = _ticket(basic_world)
    account = _account()
    prior_timestamp = int(time.time()) - 5
    channel_message = WhatsappMessage.objects.create(
        ticket=ticket,
        account=account,
        direction=WhatsappMessage.Direction.OUTBOUND,
        body="Template body",
        external_message_id="wamid.monotonic",
        delivery_status="delivered",
        raw_payload={"status_timestamp": prior_timestamp},
    )
    client = APIClient()

    newer_lower = _meta_status_raw(
        account,
        message_id="wamid.monotonic",
        delivery_status="sent",
        issued_at=prior_timestamp + 1,
    )
    older_higher = _meta_status_raw(
        account,
        message_id="wamid.monotonic",
        delivery_status="read",
        issued_at=prior_timestamp - 1,
    )
    for raw_body in (newer_lower, older_higher):
        response = client.generic(
            "POST",
            "/api/v1/integrations/whatsapp/webhook/",
            raw_body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_meta_signature(raw_body),
        )
        assert response.status_code == 200

    channel_message.refresh_from_db()
    assert channel_message.delivery_status == "delivered"
    assert channel_message.raw_payload["status_timestamp"] == prior_timestamp
    assert (
        AuditEvent.objects.filter(
            object_id=str(ticket.id),
            action="ticket.message.delivery_updated",
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_meta_message_id_is_database_unique_when_nonblank(
    basic_world: dict[str, Any],
) -> None:
    from django.db import IntegrityError, transaction

    account = _account()
    WhatsappMessage.objects.create(
        account=account,
        direction=WhatsappMessage.Direction.INBOUND,
        body="first",
        external_message_id="wamid.database-unique",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        WhatsappMessage.objects.create(
            account=account,
            direction=WhatsappMessage.Direction.INBOUND,
            body="duplicate",
            external_message_id="wamid.database-unique",
        )


@pytest.mark.django_db
@pytest.mark.parametrize("groups", ["", "auditors", "it-agents"])
def test_send_denies_roleless_auditor_and_cross_domain_before_provider(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    groups: str,
) -> None:
    ticket = _ticket(basic_world)
    _account()
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client(f"denied-{groups or 'roleless'}", groups).post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": ["ready"],
        },
        format="json",
    )

    assert response.status_code in {403, 404}
    assert provider.fetch_count == 0
    assert provider.sent == []
    assert WhatsappMessage.objects.count() == 0
    assert TicketMessage.objects.filter(ticket=ticket).count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("consent", "opted_out"),
    [(False, False), (True, True)],
)
def test_send_requires_active_contact_consent(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    consent: bool,
    opted_out: bool,
) -> None:
    ticket = _ticket(basic_world, consent=consent, opted_out=opted_out)
    _account()
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("consent-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": ["ready"],
        },
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "whatsapp_consent_required"
    assert provider.fetch_count == 0
    assert provider.sent == []
    assert WhatsappMessage.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("account_domain", "active", "access_token", "business_id"),
    [
        ("it", True, "account-access-token", "it-business"),
        ("operational", False, "account-access-token", "ops-business"),
        ("operational", True, "", "ops-business"),
        ("operational", True, "account-access-token", ""),
    ],
)
def test_send_requires_active_same_domain_account_token_before_provider(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    account_domain: str,
    active: bool,
    access_token: str,
    business_id: str,
) -> None:
    ticket = _ticket(basic_world)
    _account(
        domain=account_domain,
        active=active,
        access_token=access_token,
        business_id=business_id,
    )
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("account-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": ["ready"],
        },
        format="json",
    )

    assert response.status_code == 503
    assert response.json()["code"] == "whatsapp_account_unavailable"
    assert provider.fetch_count == 0
    assert provider.sent == []
    assert WhatsappMessage.objects.count() == 0


@pytest.mark.django_db
def test_authorized_template_send_persists_channel_and_canonical_events(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _ticket(basic_world)
    account = _account()
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("send-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": ["ready for collection"],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "sent",
        "external_message_id": "wamid.template-test",
    }
    assert provider.fetched == [
        {
            "account_token": account.access_token,
            "business_id": account.business_id,
        }
    ]
    channel_message = WhatsappMessage.objects.get(ticket=ticket)
    ticket_message = TicketMessage.objects.get(ticket=ticket)
    event = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.message.created",
    )
    delivery_event = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.message.delivery_updated",
    )
    assert channel_message.account == account
    assert channel_message.to_number == ticket.requester.phone_e164
    assert channel_message.external_message_id == "wamid.template-test"
    assert channel_message.delivery_status == "sent"
    assert channel_message.body == "Your case update is ready for collection."
    assert ticket_message.external_message_id == "wamid.template-test"
    assert ticket_message.body_text == channel_message.body
    assert event.actor_subject == "test:send-agent"
    assert event.payload["metadata"] == {
        "channel": "whatsapp",
        "template_name": "case_update",
        "template_language": "en",
        "delivery_status": "pending",
    }
    assert delivery_event.payload["metadata"] == {
        "channel": "whatsapp",
        "provider_message_id": "wamid.template-test",
    }
    assert (
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id),
            event_type="ticket.message.created",
        ).count()
        == 1
    )
    assert (
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id),
            event_type="ticket.message.delivery_updated",
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_authorized_send_is_durable_before_the_provider_is_called(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _ticket(basic_world)
    _account()

    class ObservingProvider(StubProvider):
        observed_pending_attempt = False

        def send_template(self, **kwargs: object) -> dict[str, str]:
            assert TicketMessage.objects.filter(
                ticket=ticket,
                direction=TicketMessage.Direction.OUTBOUND,
                delivery_status="pending",
            ).exists()
            assert WhatsappMessage.objects.filter(
                ticket=ticket,
                direction=WhatsappMessage.Direction.OUTBOUND,
                delivery_status="pending",
            ).exists()
            assert AuditEvent.objects.filter(
                object_id=str(ticket.id),
                action="ticket.message.created",
            ).exists()
            assert OutboxEvent.objects.filter(
                aggregate_id=str(ticket.id),
                event_type="ticket.message.created",
            ).exists()
            self.observed_pending_attempt = True
            return super().send_template(**kwargs)

    provider = ObservingProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("durable-send-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": ["ready"],
        },
        format="json",
    )

    assert response.status_code == 200
    assert provider.observed_pending_attempt is True


@pytest.mark.django_db(transaction=True)
def test_authorized_send_commits_attempt_before_template_discovery(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _ticket(basic_world)
    _account()

    class ObservingDiscoveryProvider(StubProvider):
        observed_discovery_attempt = False

        def fetch_templates(
            self,
            *,
            account_token: str = "",
            business_id: str = "",
        ) -> list[dict[str, object]]:
            assert connection.in_atomic_block is False
            attempt = WhatsappMessage.objects.get(ticket=ticket)
            assert attempt.delivery_status == "pending"
            assert attempt.body == ""
            assert attempt.raw_payload == {
                "phase": "template_discovery",
                "template_name": "case_update",
                "template_language": "en",
                "template_parameters": ["ready"],
                "retryable": True,
            }
            assert TicketMessage.objects.filter(ticket=ticket).count() == 0
            self.observed_discovery_attempt = True
            return super().fetch_templates(
                account_token=account_token,
                business_id=business_id,
            )

    provider = ObservingDiscoveryProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client(
        "durable-discovery-agent",
        "ops-agents",
    ).post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": ["ready"],
        },
        format="json",
    )

    assert response.status_code == 200
    assert provider.observed_discovery_attempt is True


@pytest.mark.django_db(transaction=True)
def test_template_discovery_outage_leaves_retryable_durable_attempt_without_send(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _ticket(basic_world)
    _account()

    class UnavailableDiscoveryProvider(StubProvider):
        def fetch_templates(
            self,
            *,
            account_token: str = "",
            business_id: str = "",
        ) -> list[dict[str, object]]:
            raise ProviderTemplateDiscoveryError(retryable=True)

    provider = UnavailableDiscoveryProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("discovery-outage-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": ["sensitive request value"],
        },
        format="json",
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "whatsapp_template_discovery_unavailable",
        "retryable": True,
    }
    attempt = WhatsappMessage.objects.get(ticket=ticket)
    assert attempt.delivery_status == "pending"
    assert attempt.raw_payload["phase"] == "template_discovery_failed"
    assert attempt.raw_payload["retryable"] is True
    assert attempt.raw_payload["error_code"] == ("whatsapp_template_discovery_unavailable")
    assert provider.sent == []
    assert TicketMessage.objects.filter(ticket=ticket).count() == 0
    assert "provider timeout with sensitive detail" not in str(attempt.raw_payload)


@pytest.mark.django_db
def test_provider_failure_is_persisted_without_sensitive_error_details(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _ticket(basic_world)
    _account()

    class FailingProvider(StubProvider):
        def send_template(self, **kwargs: object) -> dict[str, str]:
            return {
                "status": "failed",
                "error": "sensitive provider diagnostic",
            }

    monkeypatch.setattr("apps.whatsapp.views.get_provider", FailingProvider)

    response = _authenticated_client("failed-send-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": ["ready"],
        },
        format="json",
    )

    assert response.status_code == 502
    assert response.json() == {"status": "failed", "external_message_id": ""}
    channel_message = WhatsappMessage.objects.get(ticket=ticket)
    ticket_message = TicketMessage.objects.get(ticket=ticket)
    assert channel_message.delivery_status == "failed"
    assert ticket_message.delivery_status == "failed"
    assert "sensitive provider diagnostic" not in str(channel_message.raw_payload)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("template_status", "parameters", "expected_code"),
    [
        ("PENDING", ["ready"], "whatsapp_template_not_approved"),
        ("APPROVED", [], "whatsapp_template_parameters_invalid"),
    ],
)
def test_send_rejects_unapproved_or_malformed_template_before_delivery(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    template_status: str,
    parameters: list[str],
    expected_code: str,
) -> None:
    ticket = _ticket(basic_world)
    _account()
    provider = StubProvider()
    provider.templates[0]["status"] = template_status
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    response = _authenticated_client("template-policy-agent", "ops-agents").post(
        "/api/v1/integrations/whatsapp/send/",
        {
            "ticket_number": ticket.number,
            "template_name": "case_update",
            "language": "en",
            "parameters": parameters,
        },
        format="json",
    )

    assert response.status_code in {400, 409}
    assert response.json()["code"] == expected_code
    assert provider.fetch_count == 1
    assert provider.sent == []
    attempt = WhatsappMessage.objects.get(ticket=ticket)
    assert attempt.delivery_status == "failed"
    assert attempt.raw_payload["phase"] == "template_rejected"
    assert attempt.raw_payload["retryable"] is False
    assert attempt.raw_payload["error_code"] == expected_code
    assert TicketMessage.objects.filter(ticket=ticket).count() == 0


@pytest.mark.django_db
def test_templates_require_ticket_scope_and_configured_domain_account(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _ticket(basic_world)
    _account()
    provider = StubProvider()
    monkeypatch.setattr("apps.whatsapp.views.get_provider", lambda: provider)

    denied = _authenticated_client("template-it", "it-agents").get(
        "/api/v1/integrations/whatsapp/templates/",
        {"ticket_number": ticket.number},
    )
    allowed = _authenticated_client("template-ops", "ops-agents").get(
        "/api/v1/integrations/whatsapp/templates/",
        {"ticket_number": ticket.number},
    )

    assert denied.status_code == 404
    assert allowed.status_code == 200
    assert allowed.json() == {"templates": provider.templates}


@pytest.mark.django_db
def test_templates_endpoint_reports_provider_discovery_outage(
    basic_world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _ticket(basic_world)
    _account()

    class UnavailableDiscoveryProvider(StubProvider):
        def fetch_templates(
            self,
            *,
            account_token: str = "",
            business_id: str = "",
        ) -> list[dict[str, object]]:
            raise ProviderTemplateDiscoveryError(retryable=True)

    monkeypatch.setattr(
        "apps.whatsapp.views.get_provider",
        UnavailableDiscoveryProvider,
    )

    response = _authenticated_client("template-outage", "ops-agents").get(
        "/api/v1/integrations/whatsapp/templates/",
        {"ticket_number": ticket.number},
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "whatsapp_template_discovery_unavailable",
        "retryable": True,
    }


@pytest.mark.django_db
def test_meta_verification_challenge_requires_constant_token() -> None:
    client = APIClient()

    denied = client.get(
        "/api/v1/integrations/whatsapp/webhook/",
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"},
    )
    allowed = client.get(
        "/api/v1/integrations/whatsapp/webhook/",
        {
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token",
            "hub.challenge": "42",
        },
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.content == b"42"
