"""Assemble durable ticket records into one chronological staff timeline."""
from __future__ import annotations

from django.db.models import Q

from apps.audit.models import AuditEvent
from apps.files.models import Attachment
from apps.files.views import attachment_metadata
from apps.identity_access.models import User
from apps.workflow.models import TransitionHistory

from .models import Ticket, TicketLink, TicketMessage, TicketNote


def build_ticket_activity(ticket: Ticket) -> list[dict[str, object]]:
    """Return stable, typed activity items oldest first without audit duplicates."""
    messages = list(TicketMessage.objects.filter(ticket=ticket))
    notes = list(TicketNote.objects.filter(ticket=ticket))
    transitions = list(
        TransitionHistory.objects.filter(ticket=ticket).select_related(
            "from_status",
            "to_status",
        )
    )
    audit_events = list(
        AuditEvent.objects.filter(
            object_type="ticket",
            object_id=str(ticket.id),
            action__in=(
                "ticket.work_state.changed",
                "ticket.confidentiality.changed",
                "ticket.relationship.created",
                "ticket.transitioned",
            ),
        )
    )
    attachments = list(Attachment.objects.filter(ticket=ticket))
    relationships = list(
        TicketLink.objects.filter(
            Q(from_ticket=ticket) | Q(to_ticket=ticket)
        ).select_related("from_ticket", "to_ticket")
    )

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
        (
            event
            for event in audit_events
            if event.action == "ticket.transitioned"
        ),
        key=lambda event: (event.occurred_at, str(event.id)),
    )

    def transition_payload(transition) -> dict[str, object]:
        payload: dict[str, object] = {
            "from": transition.from_status.code if transition.from_status else None,
            "to": transition.to_status.code,
            "reason": transition.reason,
        }
        matching_event = next(
            (
                event
                for event in transition_audits
                if event.payload.get("after", {}).get("status")
                == transition.to_status.code
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

    def actor(subject: str) -> dict[str, str] | None:
        if not subject:
            return None
        return {
            "subject": subject,
            "display_name": display_names.get(subject) or subject,
        }

    items: list[dict[str, object]] = []
    items.extend(
        {
            "id": f"message:{message.id}",
            "type": "message",
            "occurred_at": message.created_at,
            "actor": actor(message.author_subject),
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
            "occurred_at": note.created_at,
            "actor": actor(note.author_subject),
            "visibility": "internal",
            "payload": {"body": note.body},
        }
        for note in notes
    )
    items.extend(
        {
            "id": f"transition:{transition.id}",
            "type": "status_transition",
            "occurred_at": transition.occurred_at,
            "actor": actor(transition.actor_subject),
            "visibility": "internal",
            "payload": transition_payload(transition),
        }
        for transition in transitions
    )
    items.extend(
        {
            "id": f"audit:{event.id}",
            "type": "work_state",
            "occurred_at": event.occurred_at,
            "actor": actor(event.actor_subject),
            "visibility": "internal",
            "payload": {
                "before": event.payload.get("before", {}),
                "after": event.payload.get("after", {}),
            },
        }
        for event in audit_events
        if event.action
        in {"ticket.work_state.changed", "ticket.confidentiality.changed"}
    )
    items.extend(
        {
            "id": f"attachment:{attachment.id}",
            "type": "attachment",
            "occurred_at": attachment.uploaded_at,
            "actor": actor(attachment.uploaded_by_subject),
            "visibility": "internal",
            "payload": attachment_metadata(attachment),
        }
        for attachment in attachments
    )
    items.extend(
        {
            "id": f"relationship:{relationship.id}",
            "type": "relationship",
            "occurred_at": relationship.created_at,
            "actor": actor(relationship_actors.get(str(relationship.id), "")),
            "visibility": "internal",
            "payload": {
                "kind": relationship.kind,
                "ticket_number": (
                    relationship.to_ticket.number
                    if relationship.from_ticket_id == ticket.id
                    else relationship.from_ticket.number
                ),
                "direction": (
                    "outgoing"
                    if relationship.from_ticket_id == ticket.id
                    else "incoming"
                ),
            },
        }
        for relationship in relationships
    )
    return sorted(items, key=lambda item: (item["occurred_at"], item["id"]))
