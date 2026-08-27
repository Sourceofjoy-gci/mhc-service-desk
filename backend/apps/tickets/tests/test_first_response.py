"""First-response delivery eligibility and PostgreSQL concurrency tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections

from apps.audit.models import AuditEvent
from apps.automation.ai_assist import AiSuggestion, apply_suggestion
from apps.sla.models import SlaPolicy
from apps.sla.services import instantiate_slas
from apps.tickets import services
from apps.tickets.models import OutboxEvent, Ticket, TicketMessage

pytestmark = pytest.mark.django_db(transaction=True)


def _ticket_with_slas(basic_world) -> Ticket:
    ticket = services.create_ticket(
        domain="operational",
        title="First response",
        description="",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(),
        office=basic_world["office"],
        channel="web",
        actor_subject="creator",
    )
    instantiate_slas(
        ticket=ticket,
        policy=SlaPolicy.objects.get(domain="operational", priority=ticket.priority),
    )
    return ticket


def test_unsent_ai_draft_does_not_complete_first_response(basic_world):
    ticket = _ticket_with_slas(basic_world)
    suggestion = AiSuggestion(
        suggestion_id="unsent-draft",
        ticket_number=ticket.number,
        kind="draft_reply",
        payload={"body_text": "Proposed but not delivered"},
        confidence=0.8,
        model_id="model-1",
        model_version="1.0",
        prompt_hash="hash",
        created_at="2026-07-27T08:00:00Z",
    )

    assert (
        apply_suggestion(
            ticket=ticket,
            suggestion=suggestion,
            approver_subject="approver-1",
        )
        is True
    )

    ticket.refresh_from_db()
    first_response = ticket.sla_instances.get(kind="first_response")
    assert TicketMessage.objects.get(ticket=ticket).delivery_status == "draft"
    assert ticket.first_responded_at is None
    assert first_response.state == "active"
    assert first_response.completed_at is None
    assert (
        AuditEvent.objects.filter(object_id=str(ticket.id), action="ticket.message.created").count()
        == 1
    )
    assert (
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id), event_type="ticket.message.created"
        ).count()
        == 1
    )


def test_concurrent_delivered_replies_choose_one_matching_first_response_timestamp(
    basic_world,
):
    ticket = _ticket_with_slas(basic_world)
    barrier = Barrier(2)

    def deliver_reply(label: str):
        close_old_connections()
        local_ticket = Ticket.objects.get(id=ticket.id)
        barrier.wait(timeout=10)
        message = services.add_message(
            ticket=local_ticket,
            direction="outbound",
            body_text=f"Delivered reply {label}",
            actor_subject=f"agent-{label}",
            delivery_status="sent",
        )
        close_old_connections()
        return message.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        message_ids = list(executor.map(deliver_reply, ("a", "b")))

    ticket.refresh_from_db()
    first_response = ticket.sla_instances.get(kind="first_response")
    assert len(set(message_ids)) == 2
    assert TicketMessage.objects.filter(ticket=ticket).count() == 2
    assert ticket.first_responded_at is not None
    assert first_response.state == "met"
    assert first_response.completed_at == ticket.first_responded_at
    assert (
        AuditEvent.objects.filter(object_id=str(ticket.id), action="ticket.message.created").count()
        == 2
    )
    assert (
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id), event_type="ticket.message.created"
        ).count()
        == 2
    )
