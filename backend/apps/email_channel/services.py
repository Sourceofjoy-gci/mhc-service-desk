"""Inbound email processing.

Provider-agnostic: a webhook posts a normalised payload. We apply
idempotency, thread matching, contact reconciliation, and either attach
the message to an existing ticket or create a new one.
"""
from __future__ import annotations

import logging
import re

import bleach
from django.db import transaction
from django.utils import timezone

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office
from apps.tickets import services as ticket_services
from apps.tickets.models import OutboxEvent, Ticket, TicketMessage
from apps.workflow.models import Status

from .models import Mailbox

logger = logging.getLogger(__name__)

ALLOWED_TAGS = [
    "a", "b", "blockquote", "br", "code", "em", "i", "li", "ol", "p",
    "pre", "strong", "ul", "u", "span", "div", "hr",
]
ALLOWED_ATTRS = {"a": ["href", "title"], "span": ["class"], "div": ["class"]}


def _parse_address(value: str) -> tuple[str, str | None]:
    """Parse ``"Name <addr@example.com>"`` -> ``("addr@example.com", "Name")``."""
    m = re.match(r"^\s*(?:\"?([^\"<]*?)\"?\s*)?<([^>]+)>\s*$", value or "")
    if m:
        return m.group(2).strip().lower(), (m.group(1) or "").strip() or None
    return (value or "").strip().lower(), None


def _thread_token_in_subject(subject: str) -> str | None:
    """Look for the platform-issued ``[OP-202607-000001]`` token in the subject."""
    m = re.search(r"\[((?:OP|IT)-\d{6}-\d{6})\]", subject or "")
    return m.group(1) if m else None


def find_target_ticket(
    *,
    message_id: str,
    in_reply_to: str,
    references: str,
    subject: str,
) -> Ticket | None:
    """Match an inbound email to an existing ticket by:
      1. A previous outbound TicketMessage with the same Message-ID
      2. The In-Reply-To / References chain
      3. The platform-issued token in the subject
    """
    if message_id:
        prev = TicketMessage.objects.filter(external_message_id=message_id).first()
        if prev:
            return prev.ticket
    for ref in (in_reply_to, references or ""):
        for piece in re.split(r"[\s,]+", ref):
            if not piece:
                continue
            m = TicketMessage.objects.filter(external_message_id=piece).first()
            if m:
                return m.ticket
    token = _thread_token_in_subject(subject)
    if token:
        return Ticket.objects.filter(number=token).first()
    return None


@transaction.atomic
def process_inbound_email(
    *,
    from_header: str,
    to_header: str,
    subject: str,
    body_text: str,
    body_html: str = "",
    message_id: str = "",
    in_reply_to: str = "",
    references: str = "",
    received_at=None,
    raw_headers: dict | None = None,
) -> dict:
    """Handle an inbound email. Returns a small dict with the outcome.

    Idempotency: if a TicketMessage with the same `message_id` exists, we
    return early with status="duplicate" (PRD FR-005).
    """
    if message_id and TicketMessage.objects.filter(external_message_id=message_id).exists():
        return {"status": "duplicate", "message_id": message_id}

    from_email, from_name = _parse_address(from_header)
    to_email, _to_name = _parse_address(to_header)
    if not from_email:
        return {"status": "error", "detail": "missing From address"}

    mailbox = Mailbox.objects.filter(address__iexact=to_email, is_active=True).first()
    if not mailbox:
        # Default to operational for unknown mailboxes (most inbound is public)
        mailbox_domain = "operational"
    else:
        mailbox_domain = mailbox.domain

    # Reconcile contact by email
    contact, _ = Contact.objects.get_or_create(
        email=from_email,
        defaults={"full_name": from_name or from_email.split("@")[0]},
    )
    if from_name and contact.full_name != from_name:
        contact.full_name = from_name
        contact.save(update_fields=["full_name"])

    target = find_target_ticket(
        message_id=in_reply_to or message_id,
        in_reply_to=in_reply_to,
        references=references,
        subject=subject,
    )

    if target is None:
        # New ticket — pick a service that actually has request types, prefer
        # GEN-INFO / IT-INC seeds so the ticket lands in a usable request type.
        candidates = list(
            Service.objects.filter(domain=mailbox_domain, is_active=True)
        ) or list(Service.objects.filter(domain="operational", is_active=True))
        service = None
        request_type = None
        preferred_codes = {"GEN-INFO", "IT-INC", "IT-ACCESS"}
        ordered = sorted(
            candidates,
            key=lambda s: (0 if s.code in preferred_codes else 1, s.code),
        )
        for cand in ordered:
            rt = RequestType.objects.filter(service=cand, is_active=True).first()
            if rt:
                service = cand
                request_type = rt
                break
        if not service or not request_type:
            return {"status": "error", "detail": "no request type for service"}
        office = Office.objects.filter(is_active=True).first()
        if not office:
            return {"status": "error", "detail": "no office configured"}
        clean_html = bleach.clean(
            body_html or "",
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            strip=True,
        )
        clean_text = bleach.clean(body_text or "", tags=[], strip=True)
        target = ticket_services.create_ticket(
            domain=mailbox_domain,
            title=(subject or "Email enquiry")[:255],
            description=clean_text,
            requester=contact,
            service=service,
            request_type=request_type,
            office=office,
            channel="email",
            source_account=to_email,
            matter_reference="",
            actor_subject=f"email:{to_email}",
            ip_address=None,
        )
        new_or_existing = "created"
    else:
        new_or_existing = "updated"

    clean_html = bleach.clean(
        body_html or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True,
    )
    ticket_services.add_message(
        ticket=target,
        direction="inbound",
        actor_subject=from_email,
        author_subject=from_email,
        author_label=from_name or from_email,
        body_text=bleach.clean(body_text or "", tags=[], strip=True),
        body_html=clean_html,
        body_html_sanitized=clean_html,
        external_message_id=message_id,
        delivery_status="received",
        event_metadata={
            "channel": "email",
            "provider_message_id": message_id,
        },
    )

    return {
        "status": new_or_existing,
        "ticket_number": target.number,
        "domain": target.domain,
    }
