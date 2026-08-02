"""Tests for the email channel: idempotency, threading, sanitisation."""
from __future__ import annotations

import pytest

from apps.email_channel.models import Mailbox
from apps.email_channel.services import process_inbound_email
from apps.tickets.models import TicketMessage

pytestmark = pytest.mark.django_db


@pytest.fixture
def mailbox(db):
    return Mailbox.objects.create(address="ops@mhc.local", domain="operational", is_active=True)


def test_new_email_creates_ticket(basic_world, mailbox):
    r = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject="Hello",
        body_text="I need help.",
        message_id="<m1@example.com>",
    )
    assert r["status"] == "created", r
    assert r["ticket_number"] == "O00001"


def test_duplicate_message_id_returns_duplicate(basic_world, mailbox):
    r1 = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject="Hello",
        body_text="I need help.",
        message_id="<m-dup@example.com>",
    )
    r2 = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject="Hello",
        body_text="I need help.",
        message_id="<m-dup@example.com>",
    )
    assert r1["status"] == "created", r1
    assert r2["status"] == "duplicate", r2


def test_in_reply_to_attaches_to_existing_ticket(basic_world, mailbox):
    r1 = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject="Hello",
        body_text="I need help.",
        message_id="<thread-1@example.com>",
    )
    ticket_number = r1["ticket_number"]
    r2 = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject="Re: Hello",
        body_text="Any update?",
        message_id="<thread-2@example.com>",
        in_reply_to="<thread-1@example.com>",
        sender_verified=True,
    )
    assert r2["status"] == "updated", r2
    assert r2["ticket_number"] == ticket_number


def test_subject_token_attach(basic_world, mailbox):
    r1 = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject="Hello",
        body_text="First message.",
        message_id="<tok-1@example.com>",
    )
    token = r1["ticket_number"]
    r2 = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject=f"Re: [{token}] question",
        body_text="Following up",
        message_id="<tok-2@example.com>",
        sender_verified=True,
    )
    assert r2["status"] == "updated", r2
    assert r2["ticket_number"] == token


def test_html_is_sanitised(basic_world, mailbox):
    r = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject="XSS test",
        body_text="Click here",
        body_html='<p>Hi</p><script>alert(1)</script><a href="javascript:doBad()">link</a>',
        message_id="<xss@example.com>",
    )
    assert r["status"] == "created", r
    msg = TicketMessage.objects.get(external_message_id="<xss@example.com>")
    assert "<script>" not in msg.body_html_sanitized
    assert "javascript:" not in msg.body_html_sanitized


def test_inbound_email_uses_canonical_message_event_without_body_or_duplicate_outbox(
    basic_world,
    mailbox,
):
    from apps.audit.models import AuditEvent
    from apps.tickets.models import OutboxEvent

    body = "Requester secret details"
    message_id = "<event@example.com>"
    result = process_inbound_email(
        from_header="Visitor <visitor@example.com>",
        to_header="ops@mhc.local",
        subject="Sensitive subject",
        body_text=body,
        body_html=f"<p>{body}</p><script>bad()</script>",
        message_id=message_id,
    )
    message = TicketMessage.objects.get(external_message_id=message_id)
    event = AuditEvent.objects.get(
        object_id=str(message.ticket_id),
        action="ticket.message.created",
    )

    assert message.body_html_sanitized == f"<p>{body}</p>bad()"
    assert event.payload["metadata"] == {
        "channel": "email",
        "provider_message_id": message_id,
    }
    assert body not in str(event.payload)
    assert "Sensitive subject" not in str(event.payload)
    assert OutboxEvent.objects.filter(
        aggregate_id=str(message.ticket_id),
        event_type="ticket.message.created",
    ).count() == 1
    assert result["status"] == "created"
