"""Assemble durable ticket records into one chronological staff timeline."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from django.db.models import Q
from rest_framework.request import Request

from apps.audit.models import AuditEvent
from apps.files.models import Attachment
from apps.files.views import attachment_metadata
from apps.identity_access.models import User
from apps.identity_access.scope import (
    AuthoritySnapshot,
    get_authority_snapshot,
    scope_ticket_queryset,
)
from apps.workflow.models import TransitionHistory

from .models import Ticket, TicketCustodyEvent, TicketLink, TicketMessage, TicketNote


class ActivityActor(TypedDict):
    subject: str
    display_name: str


class ActivityItem(TypedDict):
    id: str
    type: str
    category: str
    occurred_at: datetime
    actor: ActivityActor | None
    visibility: str
    payload: dict[str, object]


def scoped_ticket_relationships(
    ticket: Ticket,
    actor: User,
    *,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
) -> list[TicketLink]:
    """Return links whose counterpart is visible in one canonical snapshot."""
    relationships = list(
        TicketLink.objects.filter(Q(from_ticket=ticket) | Q(to_ticket=ticket)).select_related(
            "from_ticket", "to_ticket"
        )
    )
    counterpart_ids = {
        relationship.to_ticket_id
        if relationship.from_ticket_id == ticket.id
        else relationship.from_ticket_id
        for relationship in relationships
    }
    authority = snapshot or get_authority_snapshot(actor, request=request)
    visible_ids = set(
        scope_ticket_queryset(
            actor,
            Ticket.objects.filter(id__in=counterpart_ids),
            request=request,
            snapshot=authority,
        ).values_list("id", flat=True)
    )
    return [
        relationship
        for relationship in relationships
        if (
            relationship.to_ticket_id
            if relationship.from_ticket_id == ticket.id
            else relationship.from_ticket_id
        )
        in visible_ids
    ]


def build_ticket_activity(
    ticket: Ticket,
    *,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
    relationships: list[TicketLink] | None = None,
) -> list[ActivityItem]:
    """Return stable, typed activity items oldest first without audit duplicates."""
    messages = list(TicketMessage.objects.filter(ticket=ticket))
    notes = list(TicketNote.objects.filter(ticket=ticket))
    transitions = list(
        TransitionHistory.objects.filter(ticket=ticket).select_related(
            "from_status",
            "to_status",
        )
    )
    custody_events = list(TicketCustodyEvent.objects.filter(ticket=ticket))
    audit_events = list(
        AuditEvent.objects.filter(
            object_type="ticket",
            object_id=str(ticket.id),
            action__in=(
                "ticket.work_state.changed",
                "ticket.assignment.changed",
                "ticket.confidentiality.changed",
                "ticket.relationship.created",
                "ticket.transitioned",
            ),
        )
    )
    attachments = list(Attachment.objects.filter(ticket=ticket))
    custody_transition_ids = {
        event.source_record_id
        for event in custody_events
        if event.source_record_type == "workflow_transition" and event.source_record_id
    }
    custody_audit_fields: dict[str, set[str]] = {}
    owner_custody_types = {
        TicketCustodyEvent.EventType.ASSIGNED,
        TicketCustodyEvent.EventType.REASSIGNED,
        TicketCustodyEvent.EventType.UNASSIGNED,
    }
    for custody_event in custody_events:
        if custody_event.source_record_type != "audit_event" or not custody_event.source_record_id:
            continue
        represented_fields = custody_audit_fields.setdefault(custody_event.source_record_id, set())
        if (
            custody_event.event_type in owner_custody_types
            or custody_event.previous_owner is not None
            or custody_event.new_owner is not None
        ):
            represented_fields.add("assignee")
        if (
            custody_event.event_type == TicketCustodyEvent.EventType.QUEUE_CHANGED
            or custody_event.previous_queue is not None
            or custody_event.new_queue is not None
        ):
            represented_fields.add("queue")
    transitions = [
        transition
        for transition in transitions
        if str(transition.id) not in custody_transition_ids
    ]
    supplied_relationship_ids = (
        {relationship.id for relationship in relationships} if relationships is not None else None
    )
    request_actor = request.user if request is not None else None
    if isinstance(request_actor, User) and request_actor.is_authenticated:
        relationships = scoped_ticket_relationships(
            ticket,
            request_actor,
            request=request,
            snapshot=snapshot,
        )
        if supplied_relationship_ids is not None:
            relationships = [
                relationship
                for relationship in relationships
                if relationship.id in supplied_relationship_ids
            ]
    else:
        relationships = []

    relationship_actors = {
        str(event.payload.get("after", {}).get("relationship_id")): event.actor_subject
        for event in audit_events
        if event.action == "ticket.relationship.created"
    }
    actor_subjects = {
        *[message.author_subject for message in messages],
        *[note.author_subject for note in notes],
        *[transition.actor_subject for transition in transitions],
        *[event.actor_subject for event in audit_events],
        *[attachment.uploaded_by_subject for attachment in attachments],
        *relationship_actors.values(),
    }
    actor_subjects.discard("")
    display_names = dict(
        User.objects.filter(keycloak_subject__in=actor_subjects).values_list(
            "keycloak_subject",
            "display_name",
        )
    )

    transition_audits = sorted(
        (event for event in audit_events if event.action == "ticket.transitioned"),
        key=lambda event: (event.occurred_at, str(event.id)),
    )
    def transition_payload(transition: TransitionHistory) -> dict[str, object]:
        payload: dict[str, object] = {
            "from": transition.from_status.code if transition.from_status else None,
            "to": transition.to_status.code,
            "reason": transition.reason,
        }
        matching_event = next(
            (
                event
                for event in transition_audits
                if event.payload.get("after", {}).get("status") == transition.to_status.code
                and event.occurred_at >= transition.occurred_at
            ),
            None,
        )
        if matching_event is None:
            return payload
        transition_audits.remove(matching_event)
        resolution_fields = {
            "resolution_code",
            "resolution_summary",
            "resolved_at",
            "reopened_at",
        }
        before = {
            key: value
            for key, value in matching_event.payload.get("before", {}).items()
            if key in resolution_fields
        }
        after = {
            key: value
            for key, value in matching_event.payload.get("after", {}).items()
            if key in resolution_fields
        }
        if before or after:
            payload["before"] = before
            payload["after"] = after
        return payload

    def actor_details(subject: str) -> ActivityActor | None:
        if not subject:
            return None
        return {
            "subject": subject,
            "display_name": display_names.get(subject) or subject,
        }

    def custody_actor_details(event: TicketCustodyEvent) -> ActivityActor:
        """Custody records retain their actor snapshot independently of users."""
        return {
            "subject": event.actor_subject,
            "display_name": event.actor_display_name,
        }

    def custody_owner_presentation(
        owner: dict[str, object] | None,
        designations: list[str],
        team_labels: list[str],
    ) -> dict[str, object] | None:
        """Recombine the immutable owner identity and presentation snapshots."""
        if owner is None:
            return None
        return {
            **owner,
            "designations": list(designations),
            "team_labels": list(team_labels),
        }

    def custody_payload(event: TicketCustodyEvent) -> dict[str, object]:
        """Expose full immutable custody facts without looking up mutable rows."""
        payload: dict[str, object] = {
            "action": event.event_type,
            "from": (event.previous_status.get("code") if event.previous_status else None),
            "to": event.new_status.get("code") if event.new_status else None,
            "previous_owner": custody_owner_presentation(
                event.previous_owner,
                event.previous_designations,
                event.previous_team_labels,
            ),
            "new_owner": custody_owner_presentation(
                event.new_owner,
                event.new_designations,
                event.new_team_labels,
            ),
            "previous_queue": event.previous_queue,
            "new_queue": event.new_queue,
            "previous_status": event.previous_status,
            "new_status": event.new_status,
            "actor_kind": event.actor_kind,
            "source_process": event.source_process,
            "source_record_type": event.source_record_type,
            "source_record_id": event.source_record_id,
            "reason": event.reason,
        }
        matching_event = next(
            (
                audit_event
                for audit_event in transition_audits
                if audit_event.payload.get("after", {}).get("status") == payload["to"]
                and audit_event.occurred_at >= event.occurred_at
            ),
            None,
        )
        if matching_event is not None:
            transition_audits.remove(matching_event)
            resolution_fields = {
                "resolution_code",
                "resolution_summary",
                "resolved_at",
                "reopened_at",
            }
            before = {
                key: value
                for key, value in matching_event.payload.get("before", {}).items()
                if key in resolution_fields
            }
            after = {
                key: value
                for key, value in matching_event.payload.get("after", {}).items()
                if key in resolution_fields
            }
            if before or after:
                payload["before"] = before
                payload["after"] = after
        return payload

    def work_state_payload(event: AuditEvent) -> dict[str, object] | None:
        before = dict(event.payload.get("before", {}))
        after = dict(event.payload.get("after", {}))
        for key in custody_audit_fields.get(str(event.id), set()):
            before.pop(key, None)
            after.pop(key, None)
        if not before and not after:
            return None
        return {"before": before, "after": after}

    items: list[ActivityItem] = []
    items.extend(
        {
            "id": f"message:{message.id}",
            "type": "message",
            "category": "public_reply",
            "occurred_at": message.created_at,
            "actor": actor_details(message.author_subject),
            "visibility": "requester",
            "payload": {
                "direction": message.direction,
                "author_label": message.author_label,
                "body_text": message.body_text,
                "body_html_sanitized": message.body_html_sanitized,
                "delivery_status": message.delivery_status,
            },
        }
        for message in messages
    )
    items.extend(
        {
            "id": f"note:{note.id}",
            "type": "internal_note",
            "category": "internal_note",
            "occurred_at": note.created_at,
            "actor": actor_details(note.author_subject),
            "visibility": "internal",
            "payload": {"body": note.body},
        }
        for note in notes
    )
    items.extend(
        {
            "id": f"transition:{transition.id}",
            "type": "status_transition",
            "category": "workflow",
            "occurred_at": transition.occurred_at,
            "actor": actor_details(transition.actor_subject),
            "visibility": "internal",
            "payload": transition_payload(transition),
        }
        for transition in transitions
    )
    for event in audit_events:
        if event.action not in {
            "ticket.work_state.changed",
            "ticket.confidentiality.changed",
        }:
            continue
        payload = work_state_payload(event)
        if payload is None:
            continue
        items.append(
            {
                "id": f"audit:{event.id}",
                "type": "work_state",
                "category": "workflow",
                "occurred_at": event.occurred_at,
                "actor": actor_details(event.actor_subject),
                "visibility": "internal",
                "payload": payload,
            }
        )
    custody_status_types = {
        TicketCustodyEvent.EventType.STATUS_CHANGED,
        TicketCustodyEvent.EventType.REOPENED,
        TicketCustodyEvent.EventType.CLOSED,
    }
    items.extend(
        {
            "id": f"custody:{event.id}",
            "type": (
                "status_transition" if event.event_type in custody_status_types else "custody_event"
            ),
            "category": ("workflow" if event.event_type in custody_status_types else "custody"),
            "occurred_at": event.occurred_at,
            "actor": custody_actor_details(event),
            "visibility": "internal",
            "payload": custody_payload(event),
        }
        for event in custody_events
    )
    items.extend(
        {
            "id": f"attachment:{attachment.id}",
            "type": "attachment",
            "category": "attachment",
            "occurred_at": attachment.uploaded_at,
            "actor": actor_details(attachment.uploaded_by_subject),
            "visibility": "internal",
            "payload": attachment_metadata(attachment),
        }
        for attachment in attachments
    )
    items.extend(
        {
            "id": f"relationship:{relationship.id}",
            "type": "relationship",
            "category": "relationship",
            "occurred_at": relationship.created_at,
            "actor": actor_details(relationship_actors.get(str(relationship.id), "")),
            "visibility": "internal",
            "payload": {
                "kind": relationship.kind,
                "ticket_number": (
                    relationship.to_ticket.number
                    if relationship.from_ticket_id == ticket.id
                    else relationship.from_ticket.number
                ),
                "direction": (
                    "outgoing" if relationship.from_ticket_id == ticket.id else "incoming"
                ),
            },
        }
        for relationship in relationships
    )
    custody_sequences = {
        f"custody:{event.id}": event.sequence for event in custody_events
    }

    def activity_sort_key(item: ActivityItem) -> tuple[datetime, str]:
        sequence = custody_sequences.get(item["id"])
        stable_id = (
            f"custody:{sequence:020d}" if sequence is not None else item["id"]
        )
        return item["occurred_at"], stable_id

    return sorted(items, key=activity_sort_key)
