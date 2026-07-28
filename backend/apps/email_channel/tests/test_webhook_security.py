"""Trust-boundary tests for normalized email provider webhooks."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.contacts.models import Contact
from apps.email_channel.models import EmailDelivery, EmailWebhookEvent, Mailbox
from apps.tickets import services as ticket_services
from apps.tickets.models import OutboxEvent, Ticket, TicketMessage
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db

WEBHOOK_SECRET = "email-adapter-test-secret"


def _raw(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _headers(
    raw_body: bytes,
    *,
    event_id: str,
    timestamp: int | None = None,
    secret: str = WEBHOOK_SECRET,
) -> dict[str, str]:
    issued_at = timestamp if timestamp is not None else int(time.time())
    signed = f"{issued_at}.{event_id}.".encode() + raw_body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_MHC_WEBHOOK_TIMESTAMP": str(issued_at),
        "HTTP_X_MHC_WEBHOOK_EVENT_ID": event_id,
        "HTTP_X_MHC_WEBHOOK_SIGNATURE": f"sha256={digest}",
    }


def _inbound_payload(*, message_id: str) -> dict[str, object]:
    return {
        "from": "Visitor <visitor@example.com>",
        "to": "ops-webhook@mhc.local",
        "subject": "Signed email",
        "body_text": "Please help",
        "message_id": message_id,
        "sender_verified": True,
    }


def _delivery(
    basic_world: dict[str, object],
    *,
    message_id: str,
) -> EmailDelivery:
    ticket = ticket_services.create_ticket(
        domain="operational",
        title="Delivery webhook target",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.first(),
        office=basic_world["office"],
        channel="email",
        actor_subject="creator",
    )
    message = ticket_services.add_message(
        ticket=ticket,
        direction="outbound",
        body_text="Update",
        actor_subject="agent",
        delivery_status="sent",
    )
    return EmailDelivery.objects.create(
        ticket_message=message,
        to_address="visitor@example.com",
        from_address="ops@mhc.local",
        subject="Update",
        body_text="Update",
        message_id=message_id,
        status=EmailDelivery.Status.SENT,
    )


@pytest.fixture(autouse=True)
def _email_webhook_world(basic_world: object, monkeypatch: pytest.MonkeyPatch) -> None:
    Mailbox.objects.create(
        address="ops-webhook@mhc.local",
        domain="operational",
        is_active=True,
    )
    monkeypatch.setenv("EMAIL_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("CHANNEL_WEBHOOK_MAX_AGE_SECONDS", "300")


def test_inbound_email_fails_closed_when_webhook_secret_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMAIL_WEBHOOK_SECRET")
    payload = _inbound_payload(message_id="<missing-secret@example.com>")
    raw_body = _raw(payload)

    response = APIClient().generic(
        "POST",
        reverse("email-inbound"),
        raw_body,
        content_type="application/json",
        **_headers(raw_body, event_id="evt-missing-secret"),
    )

    assert response.status_code == 503
    assert Ticket.objects.count() == 0
    assert TicketMessage.objects.count() == 0


@pytest.mark.parametrize(
    "header_overrides",
    [
        {"HTTP_X_MHC_WEBHOOK_SIGNATURE": "sha256=" + "0" * 64},
        {"HTTP_X_MHC_WEBHOOK_TIMESTAMP": "not-a-timestamp"},
    ],
)
def test_inbound_email_rejects_invalid_authentication_before_mutation(
    header_overrides: dict[str, str],
) -> None:
    payload = _inbound_payload(message_id=f"<{uuid4()}@example.com>")
    raw_body = _raw(payload)
    headers = _headers(raw_body, event_id=f"evt-{uuid4()}") | header_overrides

    response = APIClient().generic(
        "POST",
        reverse("email-inbound"),
        raw_body,
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 401
    assert Ticket.objects.count() == 0
    assert TicketMessage.objects.count() == 0


def test_inbound_email_rejects_stale_signed_request_before_mutation(
) -> None:
    payload = _inbound_payload(message_id="<stale@example.com>")
    raw_body = _raw(payload)

    response = APIClient().generic(
        "POST",
        reverse("email-inbound"),
        raw_body,
        content_type="application/json",
        **_headers(
            raw_body,
            event_id="evt-stale",
            timestamp=int(time.time()) - 301,
        ),
    )

    assert response.status_code == 401
    assert Ticket.objects.count() == 0


def test_valid_email_adapter_signature_allows_inbound_mutation(
) -> None:
    payload = _inbound_payload(message_id="<valid@example.com>")
    raw_body = _raw(payload)

    response = APIClient().generic(
        "POST",
        reverse("email-inbound"),
        raw_body,
        content_type="application/json",
        **_headers(raw_body, event_id="evt-valid"),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "created"
    assert TicketMessage.objects.filter(
        external_message_id="<valid@example.com>"
    ).count() == 1


def test_email_adapter_event_id_cannot_be_replayed_with_a_new_message(
) -> None:
    first = _raw(_inbound_payload(message_id="<replay-first@example.com>"))
    second = _raw(_inbound_payload(message_id="<replay-second@example.com>"))
    client = APIClient()

    accepted = client.generic(
        "POST",
        reverse("email-inbound"),
        first,
        content_type="application/json",
        **_headers(first, event_id="evt-replay"),
    )
    replayed = client.generic(
        "POST",
        reverse("email-inbound"),
        second,
        content_type="application/json",
        **_headers(second, event_id="evt-replay"),
    )

    assert accepted.status_code == 201
    assert replayed.status_code == 200
    assert replayed.json() == {"status": "duplicate"}
    assert TicketMessage.objects.count() == 1


@pytest.mark.parametrize(
    ("protected_domain", "protected_requester_key", "sender"),
    [
        ("it", "contact", "Tester <t@example.com>"),
        ("operational", "contact", "Other <other@example.com>"),
    ],
)
def test_signed_email_cannot_thread_across_domain_or_requester(
    basic_world: dict[str, object],
    protected_domain: str,
    protected_requester_key: str,
    sender: str,
) -> None:
    service_key = "it_inc" if protected_domain == "it" else "gen_info"
    service = basic_world[service_key]
    protected = Ticket.objects.create(
        number=("IT" if protected_domain == "it" else "OP") + "-202607-999999",
        domain=protected_domain,
        title="Protected thread",
        status=Status.objects.get(domain=protected_domain, code="new"),
        channel="email",
        requester=basic_world[protected_requester_key],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )
    payload = _inbound_payload(message_id=f"<{uuid4()}@example.com>")
    payload["from"] = sender
    payload["subject"] = f"Re: [{protected.number}] private update"
    raw_body = _raw(payload)

    response = APIClient().generic(
        "POST",
        reverse("email-inbound"),
        raw_body,
        content_type="application/json",
        **_headers(raw_body, event_id=f"evt-{uuid4()}"),
    )

    assert response.status_code == 201
    assert response.json()["ticket_number"] != protected.number
    assert response.json()["domain"] == "operational"
    assert protected.messages.count() == 0


def test_signed_adapter_does_not_trust_an_unverified_from_header(
    basic_world: dict[str, object],
) -> None:
    service = basic_world["gen_info"]
    protected = Ticket.objects.create(
        number="OP-202607-999998",
        domain="operational",
        title="Protected requester thread",
        status=Status.objects.get(domain="operational", code="new"),
        channel="email",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )
    payload = _inbound_payload(message_id=f"<{uuid4()}@example.com>")
    payload["from"] = "Spoofed Rename <t@example.com>"
    payload["subject"] = f"Re: [{protected.number}] spoofed update"
    payload["sender_verified"] = False
    raw_body = _raw(payload)

    response = APIClient().generic(
        "POST",
        reverse("email-inbound"),
        raw_body,
        content_type="application/json",
        **_headers(raw_body, event_id=f"evt-{uuid4()}"),
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "error",
        "detail": "sender verification required",
    }
    basic_world["contact"].refresh_from_db()
    assert basic_world["contact"].full_name == "Tester"
    assert Contact.objects.count() == 1
    assert Ticket.objects.count() == 1
    assert TicketMessage.objects.count() == 0
    assert EmailWebhookEvent.objects.count() == 0
    assert protected.messages.count() == 0


@pytest.mark.parametrize("event_type", ["", "delivered", "complaint"])
def test_bounce_rejects_blank_or_unknown_event_type_without_mutation(
    basic_world: dict[str, object],
    event_type: str,
) -> None:
    delivery = _delivery(
        basic_world,
        message_id="<invalid-bounce-type@example.com>",
    )
    raw_body = _raw(
        {
            "message_id": delivery.message_id,
            "type": event_type,
            "error": "provider detail",
        }
    )

    response = APIClient().generic(
        "POST",
        reverse("email-bounce"),
        raw_body,
        content_type="application/json",
        **_headers(raw_body, event_id=f"evt-{uuid4()}"),
    )

    assert response.status_code == 400
    delivery.refresh_from_db()
    delivery.ticket_message.refresh_from_db()
    assert delivery.status == EmailDelivery.Status.SENT
    assert delivery.ticket_message.delivery_status == "sent"
    assert EmailWebhookEvent.objects.count() == 0


@pytest.mark.parametrize("message_id", ["", "   "])
def test_bounce_rejects_blank_message_id_even_if_a_blank_delivery_exists(
    basic_world: dict[str, object],
    message_id: str,
) -> None:
    delivery = _delivery(basic_world, message_id=message_id)
    raw_body = _raw(
        {"message_id": message_id, "type": "bounce", "error": "rejected"}
    )

    response = APIClient().generic(
        "POST",
        reverse("email-bounce"),
        raw_body,
        content_type="application/json",
        **_headers(raw_body, event_id="evt-blank-message-id"),
    )

    assert response.status_code == 400
    delivery.refresh_from_db()
    assert delivery.status == EmailDelivery.Status.SENT
    assert EmailWebhookEvent.objects.count() == 0


def test_bounce_rejects_ambiguous_delivery_lookup_without_mutation(
    basic_world: dict[str, object],
) -> None:
    message_id = "<ambiguous-delivery@example.com>"
    first = _delivery(basic_world, message_id=message_id)
    second = _delivery(basic_world, message_id=message_id)
    raw_body = _raw(
        {"message_id": message_id, "type": "failure", "error": "deferred"}
    )

    response = APIClient().generic(
        "POST",
        reverse("email-bounce"),
        raw_body,
        content_type="application/json",
        **_headers(raw_body, event_id="evt-ambiguous-delivery"),
    )

    assert response.status_code == 409
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == second.status == EmailDelivery.Status.SENT
    assert EmailWebhookEvent.objects.count() == 0


def test_signed_adapter_rejects_an_unknown_or_inactive_mailbox() -> None:
    payload = _inbound_payload(message_id=f"<{uuid4()}@example.com>")
    payload["to"] = "retired-mailbox@mhc.local"
    raw_body = _raw(payload)

    response = APIClient().generic(
        "POST",
        reverse("email-inbound"),
        raw_body,
        content_type="application/json",
        **_headers(raw_body, event_id=f"evt-{uuid4()}"),
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "error",
        "detail": "mailbox is not configured or active",
    }
    assert Ticket.objects.count() == 0


def test_unsigned_bounce_cannot_change_delivery_state(
    basic_world: dict[str, object],
) -> None:
    ticket = ticket_services.create_ticket(
        domain="operational",
        title="Bounce target",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.first(),
        office=basic_world["office"],
        channel="email",
        actor_subject="creator",
    )
    message = ticket_services.add_message(
        ticket=ticket,
        direction="outbound",
        body_text="Update",
        actor_subject="agent",
        delivery_status="sent",
    )
    delivery = EmailDelivery.objects.create(
        ticket_message=message,
        to_address="visitor@example.com",
        from_address="ops@mhc.local",
        subject="Update",
        body_text="Update",
        message_id="<bounce-target@example.com>",
        status=EmailDelivery.Status.SENT,
    )
    raw_body = _raw(
        {
            "message_id": delivery.message_id,
            "type": "bounce",
            "error": "rejected",
        }
    )

    response = APIClient().generic(
        "POST",
        reverse("email-bounce"),
        raw_body,
        content_type="application/json",
    )

    assert response.status_code == 401
    delivery.refresh_from_db()
    assert delivery.status == EmailDelivery.Status.SENT


def test_failure_then_terminal_bounce_are_distinct_idempotent_canonical_events(
    basic_world: dict[str, object],
) -> None:
    delivery = _delivery(
        basic_world,
        message_id="<signed-bounce@example.com>",
    )
    failure_body = _raw(
        {
            "message_id": delivery.message_id,
            "type": "failure",
            "error": "temporary provider failure",
        }
    )
    bounce_body = _raw(
        {
            "message_id": delivery.message_id,
            "type": "bounce",
            "error": "terminal rejection with private recipient detail",
        }
    )
    client = APIClient()

    failed = client.generic(
        "POST",
        reverse("email-bounce"),
        failure_body,
        content_type="application/json",
        **_headers(failure_body, event_id="evt-delivery-failure"),
    )
    delivery.refresh_from_db()
    delivery.ticket_message.refresh_from_db()
    assert failed.status_code == 200
    assert delivery.status == EmailDelivery.Status.FAILED
    assert delivery.ticket_message.delivery_status == "failed"

    bounced = client.generic(
        "POST",
        reverse("email-bounce"),
        bounce_body,
        content_type="application/json",
        **_headers(bounce_body, event_id="evt-terminal-bounce"),
    )
    replayed = client.generic(
        "POST",
        reverse("email-bounce"),
        bounce_body,
        content_type="application/json",
        **_headers(bounce_body, event_id="evt-terminal-bounce-replay"),
    )

    assert bounced.status_code == 200
    assert replayed.status_code == 200
    assert replayed.json() == {"status": "duplicate"}
    delivery.refresh_from_db()
    delivery.ticket_message.refresh_from_db()
    assert delivery.status == EmailDelivery.Status.BOUNCED
    assert delivery.ticket_message.delivery_status == "bounced"
    assert set(
        EmailWebhookEvent.objects.values_list("event_type", flat=True)
    ) == {"delivery_failure", "delivery_bounce"}
    events = AuditEvent.objects.filter(
        object_id=str(delivery.ticket_message.ticket_id),
        action="ticket.message.delivery_updated",
    ).order_by("occurred_at")
    assert [event.payload["after"]["delivery_status"] for event in events] == [
        "failed",
        "bounced",
    ]
    assert all("private recipient detail" not in str(event.payload) for event in events)
    outbox_events = OutboxEvent.objects.filter(
        aggregate_id=str(delivery.ticket_message.ticket_id),
        event_type="ticket.message.delivery_updated",
    ).order_by("created_at")
    assert outbox_events.count() == 2
    assert [event.payload for event in events] == [
        event.payload for event in outbox_events
    ]


def test_terminal_bounce_cannot_be_downgraded_by_later_failure(
    basic_world: dict[str, object],
) -> None:
    delivery = _delivery(
        basic_world,
        message_id="<terminal-bounce@example.com>",
    )
    bounce_body = _raw(
        {
            "message_id": delivery.message_id,
            "type": "bounce",
            "error": "terminal rejection",
        }
    )
    failure_body = _raw(
        {
            "message_id": delivery.message_id,
            "type": "failure",
            "error": "later transient failure",
        }
    )
    client = APIClient()

    bounced = client.generic(
        "POST",
        reverse("email-bounce"),
        bounce_body,
        content_type="application/json",
        **_headers(bounce_body, event_id="evt-bounce-first"),
    )
    failed_later = client.generic(
        "POST",
        reverse("email-bounce"),
        failure_body,
        content_type="application/json",
        **_headers(failure_body, event_id="evt-failure-after-bounce"),
    )

    assert bounced.status_code == 200
    assert failed_later.status_code == 200
    assert failed_later.json() == {"status": "ignored"}
    delivery.refresh_from_db()
    delivery.ticket_message.refresh_from_db()
    assert delivery.status == EmailDelivery.Status.BOUNCED
    assert delivery.error == "terminal rejection"
    assert delivery.ticket_message.delivery_status == "bounced"
    assert EmailWebhookEvent.objects.filter(
        message_id=delivery.message_id,
    ).count() == 2
    assert AuditEvent.objects.filter(
        object_id=str(delivery.ticket_message.ticket_id),
        action="ticket.message.delivery_updated",
    ).count() == 1
