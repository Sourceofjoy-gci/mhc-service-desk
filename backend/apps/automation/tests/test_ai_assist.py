"""Tests for the AI assist guard."""
from __future__ import annotations

import pytest

from apps.automation.ai_assist import AiSuggestion, apply_suggestion, record_suggestion
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_record_suggestion_creates_audit_event(basic_world):
    from apps.catalogue.models import Service, RequestType
    from apps.organisations.models import Office
    from apps.contacts.models import Contact
    from apps.tickets import services

    service = Service.objects.filter(domain="operational").first()
    request_type = RequestType.objects.filter(service=service).first() if service else None
    office = Office.objects.filter(is_active=True).first()
    contact = Contact.objects.first()
    if not (service and request_type and office and contact):
        pytest.skip("seed not available")
    ticket = services.create_ticket(
        domain="operational", title="AI test", description="",
        requester=contact, service=service, request_type=request_type, office=office, channel="web",
    )
    suggestion = AiSuggestion(
        suggestion_id="s-1",
        ticket_number=ticket.number,
        kind="draft_reply",
        payload={"body_text": "Thanks, we will follow up."},
        confidence=0.91,
        model_id="mhc-llm-stub",
        model_version="0.1.0",
        prompt_hash="abc",
        created_at="2026-07-19T10:00:00Z",
    )
    record_suggestion(ticket=ticket, suggestion=suggestion)
    assert AuditEvent.objects.filter(action="ai.suggestion.draft_reply").count() == 1


def test_apply_suggestion_requires_kind_payload(basic_world):
    from apps.catalogue.models import Service, RequestType
    from apps.organisations.models import Office
    from apps.contacts.models import Contact
    from apps.tickets import services

    service = Service.objects.filter(domain="operational").first()
    request_type = RequestType.objects.filter(service=service).first() if service else None
    office = Office.objects.filter(is_active=True).first()
    contact = Contact.objects.first()
    ticket = services.create_ticket(
        domain="operational", title="AI apply", description="",
        requester=contact, service=service, request_type=request_type, office=office, channel="web",
    )
    # Apply a classify with invalid priority — should return False (no change)
    suggestion = AiSuggestion(
        suggestion_id="s-2",
        ticket_number=ticket.number,
        kind="classify",
        payload={"priority": "P9"},
        confidence=0.5,
        model_id="m",
        model_version="0.1",
        prompt_hash="p",
        created_at="2026-07-19T10:00:00Z",
    )
    assert apply_suggestion(ticket=ticket, suggestion=suggestion, approver_subject="alice") is False
    ticket.refresh_from_db()
    assert ticket.priority == "P3"  # unchanged default


def test_record_suggestion_uses_canonical_pair_without_draft_body(basic_world):
    from apps.catalogue.models import RequestType, Service
    from apps.contacts.models import Contact
    from apps.organisations.models import Office
    from apps.tickets import services
    from apps.tickets.models import OutboxEvent

    service = Service.objects.filter(domain="operational").first()
    request_type = RequestType.objects.filter(service=service).first()
    ticket = services.create_ticket(
        domain="operational", title="AI event", description="",
        requester=Contact.objects.first(), service=service, request_type=request_type,
        office=Office.objects.filter(is_active=True).first(), channel="web",
        actor_subject="creator",
    )
    suggestion = AiSuggestion(
        suggestion_id="s-private",
        ticket_number=ticket.number,
        kind="draft_reply",
        payload={"body_text": "private generated draft"},
        confidence=0.9,
        model_id="model-1",
        model_version="1.0",
        prompt_hash="safe-hash",
        created_at="2026-07-19T10:00:00Z",
    )

    record_suggestion(ticket=ticket, suggestion=suggestion)

    audit = AuditEvent.objects.get(
        object_id=str(ticket.id), action="ai.suggestion.draft_reply",
    )
    outbox = OutboxEvent.objects.get(
        aggregate_id=str(ticket.id), event_type="ai.suggestion.draft_reply",
    )
    assert audit.payload == outbox.payload
    assert "private generated draft" not in str(audit.payload)
    assert audit.payload["metadata"]["suggestion_id"] == "s-private"


def test_approved_ai_reply_uses_message_service_and_records_one_pair(basic_world):
    from apps.catalogue.models import RequestType, Service
    from apps.contacts.models import Contact
    from apps.organisations.models import Office
    from apps.tickets import services
    from apps.tickets.models import OutboxEvent, TicketMessage

    service = Service.objects.filter(domain="operational").first()
    request_type = RequestType.objects.filter(service=service).first()
    ticket = services.create_ticket(
        domain="operational", title="AI reply", description="",
        requester=Contact.objects.first(), service=service, request_type=request_type,
        office=Office.objects.filter(is_active=True).first(), channel="web",
        actor_subject="creator",
    )
    suggestion = AiSuggestion(
        suggestion_id="s-reply", ticket_number=ticket.number, kind="draft_reply",
        payload={"body_text": "approved draft"}, confidence=0.8,
        model_id="model-1", model_version="1.0", prompt_hash="hash",
        created_at="2026-07-19T10:00:00Z",
    )

    assert apply_suggestion(
        ticket=ticket,
        suggestion=suggestion,
        approver_subject="approver-1",
    ) is True

    message = TicketMessage.objects.get(ticket=ticket, template_key="ai-draft")
    event = AuditEvent.objects.get(
        object_id=str(ticket.id), action="ticket.message.created",
    )
    assert message.author_subject == "ai:model-1"
    assert event.payload["actor"] == "approver-1"
    assert event.payload["metadata"]["suggestion_id"] == "s-reply"
    assert "approved draft" not in str(event.payload)
    assert OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type="ticket.message.created",
    ).count() == 1


@pytest.mark.parametrize(
    ("action", "params", "event_type", "before", "after"),
    [
        (
            "assign_user",
            {"username": "automation-user"},
            "ticket.assignment.changed",
            None,
            "automation-user",
        ),
        ("set_priority", {"priority": "P1"}, "ticket.priority.changed", "P3", "P1"),
    ],
)
def test_automation_ticket_changes_record_before_after_pairs(
    basic_world,
    action,
    params,
    event_type,
    before,
    after,
):
    from apps.automation.models import AutomationRule
    from apps.automation.views import evaluate_rules
    from apps.catalogue.models import RequestType, Service
    from apps.contacts.models import Contact
    from apps.identity_access.models import User
    from apps.organisations.models import Office
    from apps.tickets import services
    from apps.tickets.models import OutboxEvent

    User.objects.create(username="automation-user", keycloak_subject="automation-user")
    service = Service.objects.filter(domain="operational").first()
    ticket = services.create_ticket(
        domain="operational", title="Automation", description="",
        requester=Contact.objects.first(), service=service,
        request_type=RequestType.objects.filter(service=service).first(),
        office=Office.objects.filter(is_active=True).first(), channel="web",
        actor_subject="creator",
    )
    AutomationRule.objects.create(
        name=f"Rule {action}", trigger="ticket.created", action=action,
        action_params=params, is_active=True,
    )

    assert evaluate_rules(trigger="ticket.created", ticket=ticket) == 1

    event = AuditEvent.objects.get(object_id=str(ticket.id), action=event_type)
    field = "assignee" if action == "assign_user" else "priority"
    assert event.payload["before"] == {field: before}
    assert event.payload["after"] == {field: after}
    assert OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type=event_type,
    ).count() == 1
