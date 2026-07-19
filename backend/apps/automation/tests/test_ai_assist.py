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
