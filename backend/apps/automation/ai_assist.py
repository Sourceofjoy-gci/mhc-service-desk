"""AI assist guard (PRD §30, §35).

The platform MAY suggest draft text, classifications and similar replies,
but every AI-generated action is gated by a human approval step and is
explicitly logged. The agent never makes autonomous decisions.

This module exposes the *interface* for an AI backend (out of scope to
implement) and the audit record shape. The actual model invocation is
deliberately stubbed — the operator is expected to wire their approved
provider (with DPIA and a recorded policy review).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, asdict
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.tickets.models import OutboxEvent, Ticket, TicketMessage

logger = logging.getLogger(__name__)


@dataclass
class AiSuggestion:
    """A draft suggestion produced by an AI backend.

    None of these fields are applied to the ticket until a human approves.
    """
    suggestion_id: str
    ticket_number: str
    kind: str                # "draft_reply" | "classify" | "summarise" | "kb_suggest"
    payload: dict[str, Any]  # kind-specific output (e.g. {"body_text": "..."})
    confidence: float        # 0.0 .. 1.0
    model_id: str
    model_version: str
    prompt_hash: str         # SHA-256 of the prompt used (for audit)
    created_at: str

    def to_audit(self) -> dict:
        return asdict(self)


def record_suggestion(*, ticket: Ticket, suggestion: AiSuggestion) -> None:
    """Persist the suggestion as an audit event + outbox record.

    The application layer is responsible for ensuring the corresponding
    human approval is recorded before the suggestion is applied.
    """
    AuditEvent.objects.create(
        actor_subject=f"ai:{suggestion.model_id}",
        action=f"ai.suggestion.{suggestion.kind}",
        object_type="ticket",
        object_id=str(ticket.id),
        payload_hash=hashlib.sha256(suggestion.prompt_hash.encode()).hexdigest(),
        ip_address=None,
    )
    OutboxEvent.objects.create(
        aggregate="ticket",
        aggregate_id=str(ticket.id),
        event_type=f"ai.suggestion.{suggestion.kind}",
        payload=suggestion.to_audit(),
    )


@transaction.atomic
def apply_suggestion(*, ticket: Ticket, suggestion: AiSuggestion, approver_subject: str) -> bool:
    """Apply a previously-suggested action after a human approved it.

    Every application is audited with the approver, the suggestion id and
    the model version that produced the draft.
    """
    if suggestion.kind == "draft_reply":
        body = suggestion.payload.get("body_text", "").strip()
        if not body:
            return False
        TicketMessage.objects.create(
            ticket=ticket,
            direction="outbound",
            author_subject=f"ai:{suggestion.model_id}",
            author_label=f"AI draft approved by {approver_subject}",
            body_text=body,
            template_key="ai-draft",
            template_version=suggestion.model_version,
            delivery_status="draft",
        )
    elif suggestion.kind == "classify":
        new_priority = suggestion.payload.get("priority")
        if new_priority not in ("P1", "P2", "P3", "P4"):
            return False
        ticket.priority = new_priority
        ticket.save(update_fields=["priority", "updated_at"])
    else:
        return False

    AuditEvent.objects.create(
        actor_subject=approver_subject,
        action=f"ai.suggestion.applied.{suggestion.kind}",
        object_type="ticket",
        object_id=str(ticket.id),
        payload_hash=hashlib.sha256(suggestion.suggestion_id.encode()).hexdigest(),
        ip_address=None,
    )
    return True
