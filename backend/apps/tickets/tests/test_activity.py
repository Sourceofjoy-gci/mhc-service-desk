"""Unified staff activity read-model tests."""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from apps.audit.models import AuditEvent
from apps.files.models import Attachment
from apps.identity_access.models import User
from apps.identity_access.scope import get_authority_snapshot
from apps.sla.models import SlaInstance, SlaPolicy
from apps.tickets import services as ticket_services
from apps.tickets.activity import build_ticket_activity
from apps.tickets.api import TicketDetailSerializer
from apps.tickets.models import Ticket, TicketLink, TicketMessage, TicketNote
from apps.workflow.models import Status, TransitionHistory

pytestmark = pytest.mark.django_db


def _ticket(basic_world, *, domain="operational") -> Ticket:
    service = (
        basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    )
    return Ticket.objects.create(
        number=f"{domain[:2].upper()}-202607-{Ticket.objects.count() + 993001:06d}",
        domain=domain,
        title="Activity timeline",
        status=Status.objects.get(domain=domain, code="in_progress"),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _user(groups, *, subject="agent-1", display_name="Agent One"):
    user = User.objects.create(
        username=f"user-{uuid4().hex}",
        keycloak_subject=subject,
        display_name=display_name,
        keycloak_groups=groups,
    )
    user._groups = groups
    return user


def _seed_activity(basic_world):
    ticket = _ticket(basic_world)
    target = _ticket(basic_world)
    _user(["ops-agents"])
    start = timezone.now() - timedelta(hours=1)

    message = TicketMessage.objects.create(
        ticket=ticket,
        direction="outbound",
        author_subject="agent-1",
        author_label="Agent One",
        body_text="Requester-visible update",
        body_html_sanitized="<p>Requester-visible update</p>",
    )
    TicketMessage.objects.filter(id=message.id).update(created_at=start)
    message.refresh_from_db()

    note = TicketNote.objects.create(
        ticket=ticket,
        author_subject="agent-1",
        body="Internal investigation detail",
    )
    TicketNote.objects.filter(id=note.id).update(
        created_at=start + timedelta(minutes=1)
    )
    note.refresh_from_db()

    transition = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=Status.objects.get(domain="operational", code="triage"),
        to_status=ticket.status,
        actor_subject="agent-1",
        reason="Started",
    )
    TransitionHistory.objects.filter(id=transition.id).update(
        occurred_at=start + timedelta(minutes=2)
    )
    transition.refresh_from_db()

    audit = AuditEvent.objects.create(
        actor_subject="agent-1",
        action="ticket.work_state.changed",
        object_type="ticket",
        object_id=str(ticket.id),
        payload={
            "before": {"team": "Intake"},
            "after": {"team": "Estates"},
        },
        payload_hash="a" * 64,
    )
    AuditEvent.objects.filter(id=audit.id).update(
        occurred_at=start + timedelta(minutes=3)
    )
    audit.refresh_from_db()

    attachment = Attachment.objects.create(
        ticket=ticket,
        object_key=f"attachments/{uuid4().hex}",
        filename="evidence.pdf",
        content_type="application/pdf",
        size_bytes=1234,
        checksum_sha256="b" * 64,
        scan_status="clean",
        uploaded_by_subject="agent-1",
    )
    Attachment.objects.filter(id=attachment.id).update(
        uploaded_at=start + timedelta(minutes=4)
    )
    attachment.refresh_from_db()

    relationship = TicketLink.objects.create(
        from_ticket=ticket,
        to_ticket=target,
        kind="related",
    )
    TicketLink.objects.filter(id=relationship.id).update(
        created_at=start + timedelta(minutes=5)
    )
    relationship.refresh_from_db()
    return ticket, message, note, transition, audit, attachment, relationship


def test_activity_is_stable_typed_chronological_and_deduplicated(basic_world):
    ticket, message, note, transition, audit, attachment, relationship = _seed_activity(
        basic_world
    )
    viewer = User.objects.get(keycloak_subject="agent-1")
    viewer._groups = ["ops-agents"]
    request = Request(APIRequestFactory().get(f"/tickets/{ticket.number}/activity/"))
    request.user = viewer

    activity = build_ticket_activity(ticket, request=request)

    assert [item["id"] for item in activity] == [
        f"message:{message.id}",
        f"note:{note.id}",
        f"transition:{transition.id}",
        f"audit:{audit.id}",
        f"attachment:{attachment.id}",
        f"relationship:{relationship.id}",
    ]
    assert len({item["id"] for item in activity}) == len(activity)
    assert [(item["occurred_at"], item["id"]) for item in activity] == sorted(
        (item["occurred_at"], item["id"]) for item in activity
    )
    assert [item["type"] for item in activity] == [
        "message",
        "internal_note",
        "status_transition",
        "work_state",
        "attachment",
        "relationship",
    ]
    assert [item["visibility"] for item in activity] == [
        "requester",
        "internal",
        "internal",
        "internal",
        "internal",
        "internal",
    ]
    assert all(item["actor"] == {
        "subject": "agent-1",
        "display_name": "Agent One",
    } for item in activity[:-1])
    assert activity[-1]["actor"] is None
    assert activity[0]["payload"]["body_text"] == "Requester-visible update"
    assert activity[1]["payload"] == {"body": "Internal investigation detail"}
    assert activity[2]["payload"] == {
        "from": "triage",
        "to": "in_progress",
        "reason": "Started",
    }
    assert activity[3]["payload"] == {
        "before": {"team": "Intake"},
        "after": {"team": "Estates"},
    }
    assert activity[4]["payload"]["filename"] == "evidence.pdf"
    assert activity[5]["payload"] == {
        "kind": "related",
        "ticket_number": ticket.links_from.get().to_ticket.number,
        "direction": "outgoing",
    }


@pytest.mark.parametrize(
    ("counterpart_domain", "counterpart_confidentiality"),
    [
        ("operational", "restricted"),
        ("it", "normal"),
    ],
)
def test_direct_activity_without_authority_omits_relationship_identifiers(
    basic_world,
    counterpart_domain,
    counterpart_confidentiality,
):
    visible = _ticket(basic_world)
    hidden = _ticket(basic_world, domain=counterpart_domain)
    hidden.confidentiality = counterpart_confidentiality
    hidden.save(update_fields=["confidentiality"])
    TicketLink.objects.create(from_ticket=visible, to_ticket=hidden, kind="related")

    activity = build_ticket_activity(visible)

    assert hidden.number not in str(activity)
    assert not [item for item in activity if item["type"] == "relationship"]


@pytest.mark.parametrize(
    ("counterpart_domain", "counterpart_confidentiality"),
    [
        ("operational", "restricted"),
        ("it", "normal"),
    ],
)
def test_relationship_override_cannot_bypass_authenticated_activity_scope(
    basic_world,
    counterpart_domain,
    counterpart_confidentiality,
):
    visible = _ticket(basic_world)
    hidden = _ticket(basic_world, domain=counterpart_domain)
    hidden.confidentiality = counterpart_confidentiality
    hidden.save(update_fields=["confidentiality"])
    relationship = TicketLink.objects.create(
        from_ticket=visible,
        to_ticket=hidden,
        kind="related",
    )
    actor = _user(["ops-agents"], subject=f"override-{counterpart_domain}")
    request = Request(APIRequestFactory().get(f"/tickets/{visible.number}/activity/"))
    request.user = actor

    activity = build_ticket_activity(
        visible,
        request=request,
        relationships=[relationship],
    )

    assert hidden.number not in str(activity)
    assert not [item for item in activity if item["type"] == "relationship"]


def test_activity_endpoint_is_staff_scoped_and_contains_message_and_note_bodies(
    basic_world,
):
    ticket, *_ = _seed_activity(basic_world)
    actor = User.objects.get(keycloak_subject="agent-1")
    actor._groups = ["ops-agents"]
    client = APIClient()
    client.force_authenticate(user=actor)

    response = client.get(reverse("tickets-activity", args=[ticket.number]))

    assert response.status_code == 200
    by_type = {item["type"]: item for item in response.data["results"]}
    assert by_type["message"]["payload"]["body_text"] == "Requester-visible update"
    assert by_type["internal_note"]["payload"]["body"] == "Internal investigation detail"

    anonymous = APIClient().get(reverse("tickets-activity", args=[ticket.number]))
    assert anonymous.status_code in {401, 403}


def test_activity_endpoint_hides_other_domain_ticket(basic_world):
    ticket = _ticket(basic_world, domain="it")
    actor = _user(["ops-agents"], subject="ops-only")
    client = APIClient()
    client.force_authenticate(user=actor)

    response = client.get(reverse("tickets-activity", args=[ticket.number]))

    assert response.status_code == 404


def test_reopen_activity_preserves_the_prior_resolution(basic_world):
    ticket = _ticket(basic_world)
    actor = _user(["ops-agents"], subject="lifecycle-agent")

    ticket = ticket_services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="resolved",
        resolution_code="INFO_PROVIDED",
        resolution_summary="The requester received an answer.",
    )
    ticket = ticket_services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="reopened",
        reason="Requester supplied new information",
    )

    reopened = [
        item
        for item in build_ticket_activity(ticket)
        if item["type"] == "status_transition" and item["payload"]["to"] == "reopened"
    ][0]
    assert reopened["payload"]["before"]["resolution_code"] == "INFO_PROVIDED"
    assert reopened["payload"]["before"]["resolution_summary"] == (
        "The requester received an answer."
    )
    assert reopened["payload"]["before"]["resolved_at"] is not None
    assert reopened["payload"]["after"]["resolution_code"] == ""
    assert reopened["payload"]["after"]["resolution_summary"] == ""
    assert reopened["payload"]["after"]["resolved_at"] is None


def test_ticket_detail_adds_workspace_context_without_removing_legacy_fields(
    basic_world,
):
    ticket = _ticket(basic_world)
    assignee = _user(
        ["ops-agents"],
        subject="assigned-agent",
        display_name="Assigned Agent",
    )
    viewer = _user(["ops-agents"], subject="detail-viewer")
    ticket.assignee = assignee
    ticket.team = "Estates"
    ticket.waiting_reason = "requester"
    ticket.blocked_reason = "Awaiting signed form"
    ticket.next_action = "Call requester"
    ticket.next_action_at = timezone.now() + timedelta(days=1)
    ticket.reopened_at = timezone.now() - timedelta(minutes=5)
    ticket.save()
    target = _ticket(basic_world)
    relationship = TicketLink.objects.create(
        from_ticket=ticket,
        to_ticket=target,
        kind="related",
    )
    attachment = Attachment.objects.create(
        ticket=ticket,
        object_key=f"attachments/{uuid4().hex}",
        filename="workspace.pdf",
        content_type="application/pdf",
        size_bytes=99,
        checksum_sha256="d" * 64,
        scan_status="clean",
        uploaded_by_subject=assignee.keycloak_subject,
    )
    policy = SlaPolicy.objects.get(domain="operational", priority=ticket.priority)
    SlaInstance.objects.create(
        ticket=ticket,
        policy=policy,
        kind="resolution",
        due_at=timezone.now() + timedelta(hours=2),
    )
    client = APIClient()
    client.force_authenticate(user=viewer)

    response = client.get(reverse("tickets-detail", args=[ticket.number]))

    assert response.status_code == 200
    assert response.data["id"] == str(ticket.id)
    assert response.data["assignee"] == assignee.id
    assert response.data["assignee_detail"] == {
        "id": str(assignee.id),
        "display_name": "Assigned Agent",
    }
    assert response.data["team"] == "Estates"
    assert response.data["waiting_reason"] == "requester"
    assert response.data["blocked_reason"] == "Awaiting signed form"
    assert response.data["next_action"] == "Call requester"
    assert response.data["next_action_at"] is not None
    assert response.data["reopened_at"] is not None
    assert response.data["domain"] == "operational"
    assert response.data["confidentiality"] == "normal"
    assert response.data["relationships"] == [
        {
            "id": str(relationship.id),
            "kind": "related",
            "ticket_number": target.number,
            "direction": "outgoing",
        }
    ]
    assert response.data["attachments"][0]["id"] == str(attachment.id)
    assert response.data["attachments"][0]["download_available"] is True
    assert response.data["sla_clocks"]["first_response"]["state"] == "not_started"
    assert response.data["sla_clocks"]["resolution"]["state"] == "running"


@pytest.mark.parametrize(
    ("counterpart_domain", "counterpart_confidentiality"),
    [
        ("operational", "restricted"),
        ("it", "normal"),
    ],
)
def test_detail_and_activity_omit_out_of_scope_relationship_identifiers(
    basic_world,
    counterpart_domain,
    counterpart_confidentiality,
):
    visible = _ticket(basic_world)
    hidden = _ticket(basic_world, domain=counterpart_domain)
    hidden.confidentiality = counterpart_confidentiality
    hidden.save(update_fields=["confidentiality"])
    TicketLink.objects.create(from_ticket=visible, to_ticket=hidden, kind="related")
    actor = _user(["ops-agents"], subject=f"scoped-{counterpart_domain}")
    client = APIClient()
    client.force_authenticate(user=actor)

    detail = client.get(reverse("tickets-detail", args=[visible.number]))
    activity = client.get(reverse("tickets-activity", args=[visible.number]))

    assert detail.status_code == 200
    assert activity.status_code == 200
    assert hidden.number not in str(detail.data["relationships"])
    assert hidden.number not in str(activity.data["results"])
    assert detail.data["relationships"] == []
    assert not [
        item for item in activity.data["results"] if item["type"] == "relationship"
    ]


@pytest.mark.parametrize(
    ("initial_groups", "mutated_groups", "expected_visible"),
    [
        (["ops-agents"], ["ops-supervisors"], False),
        (["ops-supervisors"], ["ops-agents"], True),
    ],
)
def test_detail_and_activity_reuse_one_request_relationship_scope_snapshot(
    basic_world,
    initial_groups,
    mutated_groups,
    expected_visible,
):
    visible = _ticket(basic_world)
    restricted = _ticket(basic_world)
    restricted.confidentiality = "restricted"
    restricted.save(update_fields=["confidentiality"])
    TicketLink.objects.create(from_ticket=visible, to_ticket=restricted, kind="related")
    actor = _user(initial_groups, subject=f"snapshot-{expected_visible}")
    request = Request(APIRequestFactory().get(f"/tickets/{visible.number}/"))
    request.user = actor
    get_authority_snapshot(actor, request=request)
    actor._groups = mutated_groups

    detail = TicketDetailSerializer(visible, context={"request": request}).data
    activity = build_ticket_activity(visible, request=request)

    assert (restricted.number in str(detail["relationships"])) is expected_visible
    assert (restricted.number in str(activity)) is expected_visible
