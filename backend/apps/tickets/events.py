"""Canonical audit and transactional-outbox recording for ticket mutations."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import transaction

from apps.audit.models import AuditEvent

from .models import OutboxEvent, Ticket


def _changed_values(
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    changed = {
        key
        for key in before.keys() | after.keys()
        if before.get(key) != after.get(key)
    }
    return (
        {key: before.get(key) for key in changed if key in before},
        {key: after.get(key) for key in changed if key in after},
    )


@transaction.atomic
def record_ticket_event(
    *,
    ticket: Ticket,
    actor_subject: str,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> tuple[AuditEvent, OutboxEvent]:
    """Write one matching audit/outbox pair for a material ticket mutation."""
    changed_before, changed_after = _changed_values(before, after)
    raw_payload = {
        "ticket_number": ticket.number,
        "actor": actor_subject,
        "before": changed_before,
        "after": changed_after,
        "metadata": metadata or {},
    }
    canonical = json.dumps(
        raw_payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    payload = json.loads(canonical)
    audit = AuditEvent.objects.create(
        actor_subject=actor_subject,
        action=action,
        object_type="ticket",
        object_id=str(ticket.id),
        payload=payload,
        payload_hash=hashlib.sha256(canonical).hexdigest(),
        ip_address=ip_address,
    )
    outbox = OutboxEvent.objects.create(
        aggregate="ticket",
        aggregate_id=str(ticket.id),
        event_type=action,
        payload=payload,
    )
    return audit, outbox
