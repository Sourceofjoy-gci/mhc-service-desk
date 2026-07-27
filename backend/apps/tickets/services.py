"""Ticket service — numbering, creation, transitions.

All ticket state changes go through these service functions so that
invariants are enforced inside a single transaction (PRD §25.3).
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact, VerificationToken
from apps.organisations.models import Office
from apps.workflow.models import Status, Transition, TransitionHistory

from .events import record_ticket_event
from .models import OutboxEvent, Ticket, TicketLink, TicketMessage, TicketNote, Watcher

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Numbering
# -----------------------------------------------------------------------------

@dataclass
class NumberingConfig:
    operational_prefix: str = "OP"
    it_prefix: str = "IT"
    width: int = 6

    def format(self, domain: str, year: int, month: int, seq: int) -> str:
        prefix = self.operational_prefix if domain == "operational" else self.it_prefix
        return f"{prefix}-{year:04d}{month:02d}-{seq:0{self.width}d}"


def next_ticket_number(domain: str, when: datetime | None = None) -> str:
    """Atomically allocate the next ticket number for a domain.

    Counts existing tickets in the same year+month to keep numbers sequential
    and human-readable. For high-throughput write workloads, replace this
    with a database sequence (M5+).
    """
    when = when or timezone.now()
    cfg = NumberingConfig()
    prefix = cfg.format(domain, when.year, when.month, 0)[:8]  # e.g. "OP-202607"
    seq = (
        Ticket.objects.filter(
            domain=domain,
            number__startswith=prefix,
        ).count()
        + 1
    )
    return cfg.format(domain, when.year, when.month, seq)


# -----------------------------------------------------------------------------
# Creation
# -----------------------------------------------------------------------------

@transaction.atomic
def create_ticket(
    *,
    domain: str,
    title: str,
    description: str,
    requester: Contact,
    service: Service,
    request_type: RequestType,
    office: Office,
    channel: str,
    source_account: str = "",
    matter_reference: str = "",
    priority: str | None = None,
    initial_status_code: str = "new",
    custom_fields: dict[str, Any] | None = None,
    actor_subject: str = "system",
    ip_address: str | None = None,
) -> Ticket:
    """Create a ticket, its initial acknowledgement, an outbox event, and
    return the saved aggregate."""
    status = Status.objects.get(domain=domain, code=initial_status_code)
    number = next_ticket_number(domain)
    ticket = Ticket.objects.create(
        number=number,
        domain=domain,
        title=title,
        description=description,
        status=status,
        priority=priority or request_type.default_priority,
        channel=channel,
        source_account=source_account,
        requester=requester,
        service=service,
        request_type=request_type,
        office=office,
        matter_reference=matter_reference,
        custom_fields=custom_fields or {},
        acknowledged_at=timezone.now(),
    )
    TransitionHistory.objects.create(
        ticket=ticket,
        from_status=None,
        to_status=status,
        actor_subject=actor_subject,
        reason="Ticket created",
    )
    record_ticket_event(
        ticket=ticket,
        actor_subject=actor_subject,
        action="ticket.created",
        before={},
        after={
            "domain": domain,
            "channel": channel,
            "requester_id": str(requester.id),
            "title": title,
        },
        ip_address=ip_address,
    )
    logger.info("ticket_created", extra={"correlation_id": number})
    return ticket


# -----------------------------------------------------------------------------
# Transitions
# -----------------------------------------------------------------------------

class TransitionError(Exception):
    """Raised when a requested transition is invalid."""


@transaction.atomic
def transition_ticket(
    *,
    ticket: Ticket,
    to_status_code: str,
    actor_subject: str,
    reason: str = "",
    resolution_code: str = "",
    resolution_summary: str = "",
    extra: dict[str, Any] | None = None,
) -> Ticket:
    """Validate and apply a workflow transition.

    Raises TransitionError on invalid moves; emits a `ticket.transitioned`
    outbox event so downstream systems can react.
    """
    extra = extra or {}
    target = Status.objects.get(domain=ticket.domain, code=to_status_code)
    transition = Transition.objects.filter(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status=target,
        is_active=True,
    ).first()
    if not transition:
        raise TransitionError(
            f"No transition {ticket.status.code} -> {target.code} for {ticket.domain}"
        )
    if transition.sets_resolution:
        if not (resolution_code and resolution_summary):
            raise TransitionError(
                "Resolution code and summary are required to move to this status"
            )

    previous = ticket.status
    ticket.status = target
    if transition.sets_resolution:
        ticket.resolution_code = resolution_code
        ticket.resolution_summary = resolution_summary
        ticket.resolved_at = timezone.now()
    ticket.save(
        update_fields=[
            "status",
            "resolution_code",
            "resolution_summary",
            "resolved_at",
            "updated_at",
        ]
    )

    TransitionHistory.objects.create(
        ticket=ticket,
        from_status=previous,
        to_status=target,
        actor_subject=actor_subject,
        reason=reason,
    )
    OutboxEvent.objects.create(
        aggregate="ticket",
        aggregate_id=str(ticket.id),
        event_type="ticket.transitioned",
        payload={
            "ticket_number": ticket.number,
            "from": previous.code,
            "to": target.code,
            "actor": actor_subject,
            "reason": reason,
            **({"resolution_code": resolution_code} if resolution_code else {}),
        },
    )
    return ticket


# -----------------------------------------------------------------------------
# Messages, notes, watchers, links
# -----------------------------------------------------------------------------

@transaction.atomic
def add_message(
    *,
    ticket: Ticket,
    direction: str,
    body_text: str,
    actor_subject: str,
    body_html: str = "",
    body_html_sanitized: str = "",
    author_subject: str = "",
    author_label: str = "",
    template_key: str = "",
    template_version: str = "",
    external_message_id: str = "",
    delivery_status: str = "",
    event_metadata: dict[str, Any] | None = None,
) -> TicketMessage:
    message = TicketMessage.objects.create(
        ticket=ticket,
        direction=direction,
        body_text=body_text,
        body_html=body_html,
        body_html_sanitized=body_html_sanitized,
        author_subject=author_subject or actor_subject,
        author_label=author_label,
        template_key=template_key,
        template_version=template_version,
        external_message_id=external_message_id,
        delivery_status=delivery_status,
    )
    record_ticket_event(
        ticket=ticket,
        actor_subject=actor_subject,
        action="ticket.message.created",
        before={},
        after={
            "message_id": str(message.id),
            "direction": direction,
            "character_count": len(body_text),
        },
        metadata=event_metadata,
    )
    return message


@transaction.atomic
def add_internal_note(*, ticket: Ticket, body: str, author_subject: str) -> TicketNote:
    note = TicketNote.objects.create(
        ticket=ticket,
        body=body,
        author_subject=author_subject,
    )
    record_ticket_event(
        ticket=ticket,
        actor_subject=author_subject,
        action="ticket.note.created",
        before={},
        after={
            "note_id": str(note.id),
            "type": "internal",
            "character_count": len(body),
        },
    )
    return note


def add_watcher(*, ticket: Ticket, user) -> Watcher:
    watcher, _ = Watcher.objects.get_or_create(ticket=ticket, user=user)
    return watcher


@transaction.atomic
def link_tickets(
    *,
    source: Ticket,
    target: Ticket,
    kind: str,
    actor_subject: str,
    metadata: dict[str, Any] | None = None,
) -> TicketLink:
    link = TicketLink.objects.create(from_ticket=source, to_ticket=target, kind=kind)
    record_ticket_event(
        ticket=source,
        actor_subject=actor_subject,
        action="ticket.relationship.created",
        before={},
        after={
            "relationship_id": str(link.id),
            "kind": kind,
            "target_ticket_number": target.number,
        },
        metadata=metadata,
    )
    return link


# -----------------------------------------------------------------------------
# Requester access
# -----------------------------------------------------------------------------

def issue_requester_token(
    *,
    ticket: Ticket,
    ttl_minutes: int = 60,
) -> tuple[VerificationToken, str]:
    """Return (db_record, raw_token). The raw token is shown once to the user
    and never stored — only its SHA-256 hash lives in the DB."""
    raw = secrets.token_urlsafe(32)
    import hashlib
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = timezone.now() + timezone.timedelta(minutes=ttl_minutes)
    token = VerificationToken.objects.create(
        contact=ticket.requester, token_hash=token_hash, expires_at=expires_at
    )
    return token, raw
