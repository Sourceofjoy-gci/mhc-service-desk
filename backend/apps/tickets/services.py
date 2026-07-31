"""Ticket service — numbering, creation, transitions.

All ticket state changes go through these service functions so that
invariants are enforced inside a single transaction (PRD §25.3).
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework.request import Request

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact, VerificationToken
from apps.identity_access.authority_lock import lock_user_authorities
from apps.identity_access.models import User
from apps.identity_access.scope import (
    AuthoritySnapshot,
    get_authority_snapshot,
    scope_ticket_queryset,
)
from apps.organisations.models import Office
from apps.workflow.models import Status, Transition, TransitionHistory

from .custody import (
    CustodyActor,
    CustodyEventInput,
    custody_event_type_for_transition,
    queue_snapshot,
    status_snapshot,
    user_actor,
)
from .eligibility import _has_request_local_auditor_claim, is_auditor_identity
from .events import record_ticket_event
from .models import Ticket, TicketLink, TicketMessage, TicketNote, Watcher
from .permissions import (
    can_add_ticket_content,
    can_change_confidentiality,
    can_update_work_state,
)
from .workflow import available_transitions

logger = logging.getLogger(__name__)

type JSONValue = (
    None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
)
type WorkStateValue = str | datetime | UUID | None


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
    custom_fields: dict[str, JSONValue] | None = None,
    tags: list[str] | None = None,
    actor_subject: str = "system",
    actor: User | None = None,
    ip_address: str | None = None,
) -> Ticket:
    """Create a ticket, its initial acknowledgement, an outbox event, and
    return the saved aggregate."""
    status = Status.objects.get(domain=domain, code=initial_status_code)
    number = next_ticket_number(domain)
    initial_custom_fields = custom_fields or {}
    initial_tags: list[JSONValue] = list(tags or [])
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
        custom_fields=initial_custom_fields,
        tags=initial_tags,
        acknowledged_at=timezone.now(),
    )
    history = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=None,
        to_status=status,
        actor_subject=actor_subject,
        reason="Ticket created",
    )
    created_after: dict[str, JSONValue] = {
        "domain": domain,
        "channel": channel,
        "requester_id": str(requester.id),
        "title": title,
    }
    if initial_tags:
        created_after["tags"] = initial_tags
    if initial_custom_fields:
        created_after["custom_fields"] = initial_custom_fields
    record_ticket_event(
        ticket=ticket,
        actor_subject=actor_subject,
        action="ticket.created",
        before={},
        after=created_after,
        ip_address=ip_address,
        custody_actor=(
            user_actor(actor)
            if actor is not None
            else CustodyActor.system(
                actor_subject,
                source_account or f"Intake: {channel}",
            )
        ),
        custody_events=(
            CustodyEventInput.created(
                source_process="ticket.create",
                source_record_type="workflow_transition",
                source_record_id=str(history.id),
                new_queue=queue_snapshot(ticket.queue),
                new_status=status_snapshot(status),
                occurred_at=history.occurred_at,
            ),
        ),
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
    def __init__(self, current_updated_at: datetime) -> None:
        self.current_updated_at = current_updated_at


class TicketPermissionError(Exception):
    pass


class TicketScopeError(Exception):
    """Raised when the canonical locked ticket is no longer in actor scope."""


class TicketValidationError(Exception):
    def __init__(self, fields: dict[str, list[str]]):
        self.fields = fields


@dataclass(frozen=True)
class _LockedMutationAuthority:
    actor: User
    snapshot: AuthoritySnapshot


def _lock_and_revalidate_mutation_actor(
    *,
    ticket: Ticket,
    actor: User,
    request: Request | None,
    initial_snapshot: AuthoritySnapshot,
    scope_failure_is_permission: bool = False,
) -> _LockedMutationAuthority:
    """Lock current actor facts after the ticket and re-prove ticket scope."""
    request_local_auditor = _has_request_local_auditor_claim(
        actor,
        request=request,
    )
    locked_authority = lock_user_authorities((actor.id,)).get(actor.id)
    if locked_authority is None or not locked_authority.user.is_active:
        raise TicketPermissionError
    locked_actor = locked_authority.user
    locked_snapshot = locked_authority.snapshot
    if (
        initial_snapshot.auditor_identity
        or "auditor" in initial_snapshot.capabilities
        or request_local_auditor
        or locked_snapshot.auditor_identity
        or "auditor" in locked_snapshot.capabilities
        or is_auditor_identity(locked_actor)
    ):
        raise TicketPermissionError
    if not scope_ticket_queryset(
        locked_actor,
        Ticket.objects.filter(pk=ticket.pk),
        snapshot=locked_snapshot,
    ).exists():
        if scope_failure_is_permission:
            raise TicketPermissionError
        raise TicketScopeError
    return _LockedMutationAuthority(
        actor=locked_actor,
        snapshot=locked_snapshot,
    )


WORK_STATE_FIELDS = {
    "team",
    "waiting_reason",
    "blocked_reason",
    "next_action",
    "next_action_at",
    "confidentiality",
}

FIRST_RESPONSE_DELIVERY_STATUSES = {"", "sent", "delivered"}


def _validate_work_state_changes(changes: dict[str, WorkStateValue]) -> None:
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
    ticket_id: UUID,
    actor: User,
    expected_updated_at: datetime,
    changes: dict[str, WorkStateValue],
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> Ticket:
    """Atomically validate and apply optimistic work-state changes."""
    authority = snapshot or get_authority_snapshot(actor, request=request)
    try:
        locked = (
            scope_ticket_queryset(
                actor,
                Ticket.objects.select_for_update(of=("self",)),
                snapshot=authority,
            )
            .select_related("assignee")
            .get(id=ticket_id)
        )
    except Ticket.DoesNotExist as exc:
        raise TicketScopeError from exc
    if expected_updated_at != locked.updated_at:
        raise TicketConflictError(locked.updated_at)
    locked_authority = _lock_and_revalidate_mutation_actor(
        ticket=locked,
        actor=actor,
        request=request,
        initial_snapshot=authority,
    )
    locked_actor = locked_authority.actor
    locked_snapshot = locked_authority.snapshot
    if not can_update_work_state(
        locked_actor,
        locked,
        request=request,
        snapshot=locked_snapshot,
    ):
        raise TicketPermissionError

    _validate_work_state_changes(changes)
    before: dict[str, WorkStateValue] = {}
    after: dict[str, WorkStateValue] = {}
    update_fields: list[str] = []

    for field in WORK_STATE_FIELDS:
        if field not in changes:
            continue
        current = getattr(locked, field)
        if current != changes[field]:
            if field == "confidentiality" and not can_change_confidentiality(
                locked_actor,
                ticket=locked,
                request=request,
                snapshot=locked_snapshot,
            ):
                raise TicketPermissionError
            before[field] = current
            setattr(locked, field, changes[field])
            after[field] = getattr(locked, field)
            update_fields.append(field)

    if not update_fields:
        return locked
    locked.save(update_fields=[*update_fields, "updated_at"])
    record_ticket_event(
        ticket=locked,
        actor_subject=locked_actor.keycloak_subject,
        action="ticket.work_state.changed",
        before=before,
        after=after,
    )
    return locked


@transaction.atomic
def transition_ticket(
    *,
    ticket_id: UUID,
    actor: User,
    expected_updated_at: datetime,
    to_status_code: str,
    reason: str = "",
    resolution_code: str = "",
    resolution_summary: str = "",
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> Ticket:
    """Atomically validate and apply an optimistic workflow transition."""
    authority = snapshot or get_authority_snapshot(actor, request=request)
    locked = (
        Ticket.objects.select_for_update(of=("self",))
        .select_related("status")
        .get(id=ticket_id)
    )
    if expected_updated_at != locked.updated_at:
        raise TicketConflictError(locked.updated_at)

    locked_authority = _lock_and_revalidate_mutation_actor(
        ticket=locked,
        actor=actor,
        request=request,
        initial_snapshot=authority,
        scope_failure_is_permission=True,
    )
    locked_actor = locked_authority.actor
    locked_snapshot = locked_authority.snapshot

    workflow_transition = Transition.objects.select_related("to_status").filter(
        domain=locked.domain,
        from_status=locked.status,
        to_status__code=to_status_code,
        is_active=True,
    ).first()
    if workflow_transition is None:
        raise TransitionError
    if not available_transitions(
        locked,
        locked_actor,
        request=request,
        snapshot=locked_snapshot,
    ).filter(
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
    before: dict[str, WorkStateValue] = {"status": previous.code}
    after: dict[str, WorkStateValue] = {"status": target.code}
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

    from apps.sla.services import sync_slas_for_transition

    sync_slas_for_transition(
        ticket=locked,
        from_code=previous.code,
        to_code=target.code,
        actor_subject=locked_actor.keycloak_subject,
    )

    history = TransitionHistory.objects.create(
        ticket=locked,
        from_status=previous,
        to_status=target,
        actor_subject=locked_actor.keycloak_subject,
        reason=reason,
    )
    record_ticket_event(
        ticket=locked,
        actor_subject=locked_actor.keycloak_subject,
        action="ticket.transitioned",
        before=before,
        after=after,
        metadata={"reason": reason},
        custody_actor=user_actor(locked_actor),
        custody_events=(
            CustodyEventInput(
                event_type=custody_event_type_for_transition(target.code),
                source_process="ticket.transition",
                source_record_type="workflow_transition",
                source_record_id=str(history.id),
                previous_status=status_snapshot(previous),
                new_status=status_snapshot(target),
                reason=reason,
                occurred_at=history.occurred_at,
            ),
        ),
    )
    if locked.domain == Ticket.Domain.IT and target.code in {"resolved", "closed"}:
        from .it_child import sync_child_status_to_parent

        sync_child_status_to_parent(
            child=locked,
            actor_subject=locked_actor.keycloak_subject,
        )
    return locked


# -----------------------------------------------------------------------------
# Messages, notes, watchers, links
# -----------------------------------------------------------------------------


def _lock_ticket_for_content(
    *,
    ticket_id: UUID,
    actor: User | None,
    request: Request | None,
    snapshot: AuthoritySnapshot | None,
) -> tuple[Ticket, User | None]:
    query = Ticket.objects.select_for_update(of=("self",))
    if actor is None:
        return query.get(id=ticket_id), None

    authority = snapshot or get_authority_snapshot(actor, request=request)
    try:
        locked = scope_ticket_queryset(
            actor,
            query,
            snapshot=authority,
        ).get(id=ticket_id)
    except Ticket.DoesNotExist as exc:
        raise TicketScopeError from exc
    locked_authority = _lock_and_revalidate_mutation_actor(
        ticket=locked,
        actor=actor,
        request=request,
        initial_snapshot=authority,
    )
    locked_actor = locked_authority.actor
    if not can_add_ticket_content(
        locked_actor,
        locked,
        request=request,
        snapshot=locked_authority.snapshot,
    ):
        raise TicketPermissionError
    return locked, locked_actor


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
    event_metadata: dict[str, JSONValue] | None = None,
    actor: User | None = None,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> TicketMessage:
    locked_ticket, locked_actor = _lock_ticket_for_content(
        ticket_id=ticket.id,
        actor=actor,
        request=request,
        snapshot=snapshot,
    )
    event_actor = (
        locked_actor.keycloak_subject if locked_actor is not None else actor_subject
    )
    message = TicketMessage.objects.create(
        ticket=locked_ticket,
        direction=direction,
        body_text=body_text,
        body_html=body_html,
        body_html_sanitized=body_html_sanitized,
        author_subject=author_subject or event_actor,
        author_label=author_label,
        template_key=template_key,
        template_version=template_version,
        external_message_id=external_message_id,
        delivery_status=delivery_status,
    )
    record_ticket_event(
        ticket=locked_ticket,
        actor_subject=event_actor,
        action="ticket.message.created",
        before={},
        after={
            "message_id": str(message.id),
            "direction": direction,
            "character_count": len(body_text),
        },
        metadata=event_metadata,
    )
    is_delivered_staff_reply = (
        direction == TicketMessage.Direction.OUTBOUND
        and delivery_status in FIRST_RESPONSE_DELIVERY_STATUSES
    )
    if is_delivered_staff_reply and locked_ticket.first_responded_at is None:
        from apps.sla.services import complete_sla

        locked_ticket.first_responded_at = timezone.now()
        locked_ticket.save(update_fields=["first_responded_at", "updated_at"])
        complete_sla(
            ticket=locked_ticket,
            kind="first_response",
            at=locked_ticket.first_responded_at,
        )
    return message


@transaction.atomic
def add_internal_note(
    *,
    ticket: Ticket,
    body: str,
    author_subject: str,
    actor: User | None = None,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> TicketNote:
    locked_ticket, locked_actor = _lock_ticket_for_content(
        ticket_id=ticket.id,
        actor=actor,
        request=request,
        snapshot=snapshot,
    )
    event_actor = (
        locked_actor.keycloak_subject if locked_actor is not None else author_subject
    )
    note = TicketNote.objects.create(
        ticket=locked_ticket,
        body=body,
        author_subject=event_actor,
    )
    record_ticket_event(
        ticket=locked_ticket,
        actor_subject=event_actor,
        action="ticket.note.created",
        before={},
        after={
            "note_id": str(note.id),
            "type": "internal",
            "character_count": len(body),
        },
    )
    return note


def add_watcher(*, ticket: Ticket, user: User) -> Watcher:
    watcher, _ = Watcher.objects.get_or_create(ticket=ticket, user=user)
    return watcher


@transaction.atomic
def link_tickets(
    *,
    source: Ticket,
    target: Ticket,
    kind: str,
    actor_subject: str,
    metadata: dict[str, JSONValue] | None = None,
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
    expires_at = timezone.now() + timedelta(minutes=ttl_minutes)
    token = VerificationToken.objects.create(
        contact=ticket.requester, token_hash=token_hash, expires_at=expires_at
    )
    return token, raw
