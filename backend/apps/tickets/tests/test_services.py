"""Unit tests for the tickets domain services.

Exercises ticket numbering, creation, and the workflow transition rules
(FR-038, FR-040, FR-041, FR-022).
"""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office, Region
from apps.tickets import services
from apps.tickets.models import Ticket
from apps.workflow.models import Status, Transition
from apps.workflow.shortcuts import seed_workflow_for_tests

pytestmark = pytest.mark.django_db


@pytest.fixture
def basic_world(db):
    seed_workflow_for_tests()
    region = Region.objects.create(code="TST", name="Test")
    office = Office.objects.create(region=region, code="TST-1", name="Test Office")
    service = Service.objects.create(code="TST-SVC", name="Test service", domain="operational")
    rt = RequestType.objects.create(service=service, code="TST-RT", name="Test RT", default_priority="P3")
    contact = Contact.objects.create(full_name="Tester", email="t@example.com")
    return {"office": office, "service": service, "request_type": rt, "contact": contact}


def test_ticket_numbering_is_per_domain_and_sequential(basic_world):
    a = services.create_ticket(
        domain="operational",
        title="First",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    b = services.create_ticket(
        domain="operational",
        title="Second",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    assert a.number.startswith("OP-")
    assert b.number.startswith("OP-")
    assert a.number != b.number


def test_create_ticket_records_initial_status_history(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    assert ticket.acknowledged_at is not None
    assert ticket.transition_history.count() == 1
    assert ticket.transition_history.first().from_status is None
    assert ticket.transition_history.first().to_status.code == "new"


def test_valid_transition_succeeds(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    services.transition_ticket(
        ticket=ticket, to_status_code="triage", actor_subject="tester"
    )
    assert ticket.status.code == "triage"


def test_invalid_transition_raises(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    # new -> closed is not in the workflow
    with pytest.raises(services.TransitionError):
        services.transition_ticket(
            ticket=ticket, to_status_code="closed", actor_subject="tester"
        )


def test_resolution_required_for_resolved_transition(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    services.transition_ticket(ticket=ticket, to_status_code="triage", actor_subject="t")
    services.transition_ticket(ticket=ticket, to_status_code="in_progress", actor_subject="t")
    # Resolved requires resolution_code and summary
    with pytest.raises(services.TransitionError):
        services.transition_ticket(
            ticket=ticket, to_status_code="resolved", actor_subject="t"
        )
    services.transition_ticket(
        ticket=ticket, to_status_code="resolved", actor_subject="t",
        resolution_code="INFO_PROVIDED", resolution_summary="Called the requester with the answer.",
    )
    assert ticket.status.code == "resolved"
    assert ticket.resolution_code == "INFO_PROVIDED"
    assert ticket.resolved_at is not None


def test_issue_requester_token_returns_raw_once(basic_world):
    ticket = services.create_ticket(
        domain="operational",
        title="X",
        description="",
        requester=basic_world["contact"],
        service=basic_world["service"],
        request_type=basic_world["request_type"],
        office=basic_world["office"],
        channel="web",
    )
    record, raw = services.issue_requester_token(ticket=ticket)
    assert raw and len(raw) > 20
    assert record.token_hash != raw  # we never store the raw token
