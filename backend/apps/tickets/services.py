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
from .models import Ticket, TicketLink, TicketMessage, TicketNote, Watcher
from .permissions import (
    can_change_confidentiality,
    can_reassign,
    can_update_work_state,
    eligible_assignee_queryset,
)
from .workflow import available_transitions

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

    def __init__(self, fields: dict[str, list[str]] | None = None):
        self.fields = fields or {
            "to_status": ["Select an available transition."],
        }
        super().__init__("Transition is invalid.")


class TicketConflictError(Exception):
    def __init__(self, current_updated_at):
        self.current_updated_at = current_updated_at


class TicketPermissionError(Exception):
    pass


class TicketValidationError(Exception):
    def __init__(self, fields: dict[str, list[str]]):
        self.fields = fields


WORK_STATE_FIELDS = {
    "assignee",
    "team",
    "waiting_reason",
    "blocked_reason",
    "next_action",
    "next_action_at",
    "confidentiality",
}


def _validate_work_state_changes(changes: dict[str, Any]) -> None:
    fields: dict[str, list[str]] = {}
    unknown = changes.keys() - WORK_STATE_FIELDS
    if unknown:
        fields["changes"] = ["Unsupported work-state field."]

    text_limits = {
        "team": 128,
        "waiting_reason": 64,
        "next_action": 255,
    }
    for field, limit in text_limits.items():
        if field not in changes:
            continue
        value = changes[field]
        if not isinstance(value, str):
            fields[field] = ["Must be a string."]
        elif len(value) > limit:
            fields[field] = [f"Ensure this field has no more than {limit} characters."]
    if "blocked_reason" in changes and not isinstance(changes["blocked_reason"], str):
        fields["blocked_reason"] = ["Must be a string."]
    if (
        "next_action_at" in changes
        and changes["next_action_at"] is not None
        and not isinstance(changes["next_action_at"], datetime)
    ):
        fields["next_action_at"] = ["Must be a valid datetime."]
    if (
        "confidentiality" in changes
        and changes["confidentiality"] not in Ticket.Confidentiality.values
    ):
        fields["confidentiality"] = ["Select a valid choice."]
    if fields:
        raise TicketValidationError(fields)


@transaction.atomic
def update_work_state(
    *,
    ticket_id,
    actor,
    expected_updated_at,
    changes: dict[str, Any],
) -> Ticket:
    """Atomically validate and apply optimistic work-state changes."""
    locked = (
        Ticket.objects.select_for_update(of=("self",))
        .select_related("assignee")
        .get(id=ticket_id)
    )
    if expected_updated_at != locked.updated_at:
        raise TicketConflictError(locked.updated_at)
    if not can_update_work_state(actor, locked):
        raise TicketPermissionError

    _validate_work_state_changes(changes)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    update_fields: list[str] = []

    if "assignee" in changes:
        target_id = changes["assignee"]
        if target_id is None:
            if not can_reassign(actor, ticket=locked):
                raise TicketPermissionError
        else:
            is_self_assignment = locked.assignee_id is None and target_id == actor.id
            if is_self_assignment:
                pass
            elif not can_reassign(actor, ticket=locked):
                raise TicketPermissionError
            elif not eligible_assignee_queryset(locked).filter(id=target_id).exists():
                raise TicketValidationError({"assignee": ["Select a valid assignee."]})
        before["assignee"] = locked.assignee_id
        locked.assignee_id = target_id
        after["assignee"] = locked.assignee_id
        update_fields.append("assignee")

    for field in WORK_STATE_FIELDS - {"assignee"}:
        if field not in changes:
            continue
        if field == "confidentiality" and not can_change_confidentiality(
            actor,
            ticket=locked,
        ):
            raise TicketPermissionError
        before[field] = getattr(locked, field)
        setattr(locked, field, changes[field])
        after[field] = getattr(locked, field)
        update_fields.append(field)

    locked.save(update_fields=[*update_fields, "updated_at"])
    record_ticket_event(
        ticket=locked,
        actor_subject=actor.keycloak_subject,
        action="ticket.work_state.changed",
        before=before,
        after=after,
    )
    return locked


@transaction.atomic
def transition_ticket(
    *,
    ticket_id,
    actor,
    expected_updated_at,
    to_status_code: str,
    reason: str = "",
    resolution_code: str = "",
    resolution_summary: str = "",
) -> Ticket:
    """Atomically validate and apply an optimistic workflow transition."""
    locked = (
        Ticket.objects.select_for_update(of=("self",))
        .select_related("status")
        .get(id=ticket_id)
    )
    if expected_updated_at != locked.updated_at:
        raise TicketConflictError(locked.updated_at)

    workflow_transition = Transition.objects.select_related("to_status").filter(
        domain=locked.domain,
        from_status=locked.status,
        to_status__code=to_status_code,
        is_active=True,
    ).first()
    if workflow_transition is None:
        raise TransitionError
    if not available_transitions(locked, actor).filter(
        id=workflow_transition.id
    ).exists():
        raise TicketPermissionError

    supplied_fields = {
        "reason": reason,
        "resolution_code": resolution_code,
        "resolution_summary": resolution_summary,
    }
    required = set(workflow_transition.required_fields)
    if workflow_transition.sets_resolution:
        required.update({"resolution_code", "resolution_summary"})
    missing = {
        field: ["This field is required."]
        for field in required
        if not str(supplied_fields.get(field, "")).strip()
    }
    if missing:
        raise TransitionError(missing)

    now = timezone.now()
    previous = locked.status
    target = workflow_transition.to_status
    before: dict[str, Any] = {"status": previous.code}
    after: dict[str, Any] = {"status": target.code}
    update_fields = ["status"]
    locked.status = target

    if workflow_transition.sets_resolution:
        before.update(
            {
                "resolution_code": locked.resolution_code,
                "resolution_summary": locked.resolution_summary,
                "resolved_at": locked.resolved_at,
            }
        )
        locked.resolution_code = resolution_code
        locked.resolution_summary = resolution_summary
        locked.resolved_at = now
        after.update(
            {
                "resolution_code": locked.resolution_code,
                "resolution_summary": locked.resolution_summary,
                "resolved_at": locked.resolved_at,
            }
        )
        update_fields.extend(
            ["resolution_code", "resolution_summary", "resolved_at"]
        )

    if target.code == "reopened":
        before.update(
            {
                "resolution_code": locked.resolution_code,
                "resolution_summary": locked.resolution_summary,
                "resolved_at": locked.resolved_at,
                "reopened_at": locked.reopened_at,
            }
        )
        locked.resolution_code = ""
        locked.resolution_summary = ""
        locked.resolved_at = None
        locked.reopened_at = now
        after.update(
            {
                "resolution_code": "",
                "resolution_summary": "",
                "resolved_at": None,
                "reopened_at": locked.reopened_at,
            }
        )
        update_fields.extend(
            ["resolution_code", "resolution_summary", "resolved_at", "reopened_at"]
        )

    if target.code == "closed":
        before["closed_at"] = locked.closed_at
        locked.closed_at = now
        after["closed_at"] = locked.closed_at
        update_fields.append("closed_at")

    locked.save(update_fields=[*dict.fromkeys(update_fields), "updated_at"])

    TransitionHistory.objects.create(
        ticket=locked,
        from_status=previous,
        to_status=target,
        actor_subject=actor.keycloak_subject,
        reason=reason,
    )
    record_ticket_event(
        ticket=locked,
        actor_subject=actor.keycloak_subject,
        action="ticket.transitioned",
        before=before,
        after=after,
        metadata={"reason": reason},
    )
    return locked


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
