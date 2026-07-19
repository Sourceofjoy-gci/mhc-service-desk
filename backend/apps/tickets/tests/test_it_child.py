"""Tests for the IT child-ticket sanitised pattern (PRD §11.4)."""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office, Region
from apps.tickets import services, it_child
from apps.tickets.models import TicketLink
from apps.workflow.shortcuts import seed_workflow_for_tests

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(basic_world, db):
    """basic_world already seeds workflow and SLA. Add custom request types."""
    op_rt = RequestType.objects.create(service=basic_world["gen_info"], code="X", name="X", default_priority="P3")
    it_rt = RequestType.objects.create(service=basic_world["it_inc"], code="Y", name="Y", default_priority="P3")
    return {**basic_world, "op_rt": op_rt, "it_rt": it_rt}


def test_create_it_child_records_link_and_parent_status(world):
    parent = services.create_ticket(
        domain="operational", title="Email issue", description="",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email",
    )
    child = it_child.create_it_child_ticket(
        parent=parent, summary="Investigate email routing", requester=world["contact"],
        requester_office=world["office"], technical_priority="P2", actor_subject="tester",
    )
    assert child.domain == "it"
    assert child.number.startswith("IT-")
    assert TicketLink.objects.filter(from_ticket=child, to_ticket=parent, kind="it_child").exists()
    parent.refresh_from_db()
    assert parent.status.code == "waiting_it"
    assert parent.waiting_reason == "Waiting for IT"


def test_child_copies_only_approved_fields(world):
    parent = services.create_ticket(
        domain="operational", title="X", description="PRIVATE: not for IT",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email", matter_reference="EST-9999",
    )
    child = it_child.create_it_child_ticket(
        parent=parent, summary="Investigate", requester=world["contact"],
        requester_office=world["office"], technical_priority="P3",
        carry_matter_reference=True, actor_subject="tester",
    )
    assert child.description == ""
    assert "PRIVATE" not in child.title
    assert child.matter_reference == "EST-9999"


def test_child_resolution_syncs_parent_to_in_progress(world):
    parent = services.create_ticket(
        domain="operational", title="X", description="",
        requester=world["contact"], service=world["gen_info"], request_type=world["op_rt"],
        office=world["office"], channel="email",
    )
    child = it_child.create_it_child_ticket(
        parent=parent, summary="Investigate", requester=world["contact"],
        requester_office=world["office"], technical_priority="P3", actor_subject="tester",
    )
    from apps.workflow.models import Status
    target = Status.objects.get(domain="it", code="resolved")
    child.status = target
    child.resolution_code = "DONE"
    child.resolution_summary = "Fixed"
    child.resolved_at = timezone.now()
    child.save()
    it_child.sync_child_status_to_parent(child=child, actor_subject="tester")
    parent.refresh_from_db()
    assert parent.status.code == "in_progress"
    assert parent.waiting_reason == ""
