"""Canonical append-only custody records for ticket lifecycle changes."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Ticket, TicketCustodyEvent


def _utc_timestamp(value: datetime) -> str:
    """Return the ledger's stable, six-place UTC time representation."""
    if timezone.is_naive(value):
        value = timezone.make_aware(value, UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class CustodyActor:
    kind: str
    subject: str
    display_name: str

    @classmethod
    def user(cls, subject: str, display_name: str) -> CustodyActor:
        return cls(
            kind=TicketCustodyEvent.ActorKind.USER,
            subject=subject,
            display_name=display_name,
        )

    @classmethod
    def system(cls, process: str, display_name: str) -> CustodyActor:
        return cls(
            kind=TicketCustodyEvent.ActorKind.SYSTEM,
            subject=process,
            display_name=display_name,
        )

    def as_json(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "display_name": self.display_name,
        }


@dataclass(frozen=True)
class CustodyParty:
    id: str
    subject: str
    display_name: str
    designations: tuple[str, ...] = ()
    team_labels: tuple[str, ...] = ()

    def as_json(self) -> dict[str, str | list[str]]:
        return {
            "id": self.id,
            "subject": self.subject,
            "display_name": self.display_name,
            "designations": list(self.designations),
            "team_labels": list(self.team_labels),
        }


@dataclass(frozen=True)
class CustodyQueue:
    id: str
    label: str

    def as_json(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label}


@dataclass(frozen=True)
class CustodyStatus:
    code: str
    label: str

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "label": self.label}


@dataclass(frozen=True)
class CustodyEventInput:
    event_type: str
    source_process: str
    source_record_type: str = ""
    source_record_id: str = ""
    previous_owner: CustodyParty | None = None
    new_owner: CustodyParty | None = None
    previous_queue: CustodyQueue | None = None
    new_queue: CustodyQueue | None = None
    previous_status: CustodyStatus | None = None
    new_status: CustodyStatus | None = None
    reason: str = ""
    occurred_at: datetime | None = None

    @classmethod
    def created(cls, *, source_process: str, **kwargs: Any) -> CustodyEventInput:
        return cls(
            event_type=TicketCustodyEvent.EventType.CREATED,
            source_process=source_process,
            **kwargs,
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "source_process": self.source_process,
            "source_record_type": self.source_record_type,
            "source_record_id": self.source_record_id,
            "previous_owner": self.previous_owner.as_json() if self.previous_owner else None,
            "new_owner": self.new_owner.as_json() if self.new_owner else None,
            "previous_queue": self.previous_queue.as_json() if self.previous_queue else None,
            "new_queue": self.new_queue.as_json() if self.new_queue else None,
            "previous_status": self.previous_status.as_json() if self.previous_status else None,
            "new_status": self.new_status.as_json() if self.new_status else None,
            "reason": self.reason,
            "occurred_at": _utc_timestamp(self.occurred_at) if self.occurred_at else None,
        }


def _chain_payload(
    *,
    ticket_id: str,
    sequence: int,
    event_type: str,
    occurred_at: datetime,
    actor_kind: str,
    actor_subject: str,
    actor_display_name: str,
    source_process: str,
    source_record_type: str,
    source_record_id: str,
    previous_owner: dict[str, str] | None,
    new_owner: dict[str, str] | None,
    previous_queue: dict[str, str] | None,
    new_queue: dict[str, str] | None,
    previous_status: dict[str, str] | None,
    new_status: dict[str, str] | None,
    previous_designations: list[str],
    new_designations: list[str],
    previous_team_labels: list[str],
    new_team_labels: list[str],
    reason: str,
    previous_hash: str,
) -> dict[str, object]:
    return {
        "ticket_id": ticket_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": _utc_timestamp(occurred_at),
        "actor_kind": actor_kind,
        "actor_subject": actor_subject,
        "actor_display_name": actor_display_name,
        "source_process": source_process,
        "source_record_type": source_record_type,
        "source_record_id": source_record_id,
        "previous_owner": previous_owner,
        "new_owner": new_owner,
        "previous_queue": previous_queue,
        "new_queue": new_queue,
        "previous_status": previous_status,
        "new_status": new_status,
        "previous_designations": previous_designations,
        "new_designations": new_designations,
        "previous_team_labels": previous_team_labels,
        "new_team_labels": new_team_labels,
        "reason": reason,
        "previous_hash": previous_hash,
    }


def _event_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _party_snapshot(party: CustodyParty | None) -> dict[str, str] | None:
    if party is None:
        return None
    return {
        "id": party.id,
        "subject": party.subject,
        "display_name": party.display_name,
    }


def _snapshot(value: CustodyQueue | CustodyStatus | None) -> dict[str, str] | None:
    return value.as_json() if value else None


def _party_values(party: CustodyParty | None, attribute: str) -> list[str]:
    return list(getattr(party, attribute)) if party else []


@transaction.atomic
def record_custody_events(
    *,
    ticket: Ticket,
    actor: CustodyActor,
    events: Sequence[CustodyEventInput],
) -> list[TicketCustodyEvent]:
    """Append custody events in order while holding the aggregate row lock."""
    locked_ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    last_event = (
        TicketCustodyEvent._base_manager.filter(ticket=locked_ticket)
        .order_by("-sequence", "-id")
        .first()
    )
    sequence = last_event.sequence if last_event else 0
    previous_hash = last_event.event_hash if last_event else ""
    recorded: list[TicketCustodyEvent] = []

    for event_input in events:
        sequence += 1
        occurred_at = event_input.occurred_at or timezone.now()
        previous_owner = _party_snapshot(event_input.previous_owner)
        new_owner = _party_snapshot(event_input.new_owner)
        previous_queue = _snapshot(event_input.previous_queue)
        new_queue = _snapshot(event_input.new_queue)
        previous_status = _snapshot(event_input.previous_status)
        new_status = _snapshot(event_input.new_status)
        previous_designations = _party_values(event_input.previous_owner, "designations")
        new_designations = _party_values(event_input.new_owner, "designations")
        previous_team_labels = _party_values(event_input.previous_owner, "team_labels")
        new_team_labels = _party_values(event_input.new_owner, "team_labels")
        payload = _chain_payload(
            ticket_id=str(locked_ticket.id),
            sequence=sequence,
            event_type=event_input.event_type,
            occurred_at=occurred_at,
            actor_kind=actor.kind,
            actor_subject=actor.subject,
            actor_display_name=actor.display_name,
            source_process=event_input.source_process,
            source_record_type=event_input.source_record_type,
            source_record_id=event_input.source_record_id,
            previous_owner=previous_owner,
            new_owner=new_owner,
            previous_queue=previous_queue,
            new_queue=new_queue,
            previous_status=previous_status,
            new_status=new_status,
            previous_designations=previous_designations,
            new_designations=new_designations,
            previous_team_labels=previous_team_labels,
            new_team_labels=new_team_labels,
            reason=event_input.reason,
            previous_hash=previous_hash,
        )
        event_hash = _event_hash(payload)
        recorded_event = TicketCustodyEvent.objects.create(
            ticket=locked_ticket,
            sequence=sequence,
            event_type=event_input.event_type,
            occurred_at=occurred_at,
            actor_kind=actor.kind,
            actor_subject=actor.subject,
            actor_display_name=actor.display_name,
            source_process=event_input.source_process,
            source_record_type=event_input.source_record_type,
            source_record_id=event_input.source_record_id,
            previous_owner=previous_owner,
            new_owner=new_owner,
            previous_queue=previous_queue,
            new_queue=new_queue,
            previous_status=previous_status,
            new_status=new_status,
            previous_designations=previous_designations,
            new_designations=new_designations,
            previous_team_labels=previous_team_labels,
            new_team_labels=new_team_labels,
            reason=event_input.reason,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        recorded.append(recorded_event)
        previous_hash = event_hash

    return recorded


def verify_custody_chain(ticket: Ticket) -> bool:
    """Check every persisted custody record against the canonical chain."""
    previous_hash = ""
    expected_sequence = 1
    events = TicketCustodyEvent._base_manager.filter(ticket=ticket).order_by("sequence", "id")
    for event in events:
        if event.sequence != expected_sequence or event.previous_hash != previous_hash:
            return False
        payload = _chain_payload(
            ticket_id=str(event.ticket_id),
            sequence=event.sequence,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            actor_kind=event.actor_kind,
            actor_subject=event.actor_subject,
            actor_display_name=event.actor_display_name,
            source_process=event.source_process,
            source_record_type=event.source_record_type,
            source_record_id=event.source_record_id,
            previous_owner=event.previous_owner,
            new_owner=event.new_owner,
            previous_queue=event.previous_queue,
            new_queue=event.new_queue,
            previous_status=event.previous_status,
            new_status=event.new_status,
            previous_designations=event.previous_designations,
            new_designations=event.new_designations,
            previous_team_labels=event.previous_team_labels,
            new_team_labels=event.new_team_labels,
            reason=event.reason,
            previous_hash=previous_hash,
        )
        if event.event_hash != _event_hash(payload):
            return False
        previous_hash = event.event_hash
        expected_sequence += 1
    return True


def custody_event_type_for_transition(code: str) -> str:
    if code == "reopened":
        return TicketCustodyEvent.EventType.REOPENED
    if code == "closed":
        return TicketCustodyEvent.EventType.CLOSED
    return TicketCustodyEvent.EventType.STATUS_CHANGED
