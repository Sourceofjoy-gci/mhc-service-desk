from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.tickets.models import OutboxEvent, Ticket
from apps.workflow.models import Status, Transition, TransitionHistory

pytestmark = pytest.mark.django_db

CORRELATION_ID = "transition-test-correlation"


def _user(groups: list[str]) -> User:
    user = User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        keycloak_groups=groups,
    )
    user._groups = groups
    return user


def _ticket(basic_world, *, status_code: str = "new") -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 940001:06d}",
        domain="operational",
        title="Transition endpoint",
        status=Status.objects.get(domain="operational", code=status_code),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _supervisor(
    basic_world,
    *,
    role_key: str = "assistant-master",
) -> User:
    supervisor = User.objects.create(
        username=f"supervisor-{uuid4().hex}",
        keycloak_subject=f"supervisor-subject-{uuid4().hex}",
        display_name=role_key.replace("-", " ").title(),
        is_active=True,
    )
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_key.replace("-", " ").title(),
        scopes=[
            {
                "domain": Ticket.Domain.OPERATIONAL,
                "office": str(basic_world["office"].id),
                "service": str(basic_world["gen_info"].id),
            }
        ],
    )
    UserRole.objects.create(
        user=supervisor,
        role=role,
        office=basic_world["office"],
    )
    return supervisor


def _post(user: User, ticket: Ticket, payload: dict):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.post(
        reverse("tickets-transition", args=[ticket.number]),
        payload,
        format="json",
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )


def _assert_no_transition_side_effects(ticket: Ticket, previous_updated_at):
    ticket.refresh_from_db()
    assert ticket.status.code == "new"
    assert ticket.updated_at == previous_updated_at
    assert not TransitionHistory.objects.filter(ticket=ticket).exists()
    assert not AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.transitioned"
    ).exists()
    assert not OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type="ticket.transitioned"
    ).exists()


def test_transition_requires_updated_at(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    response = _post(actor, ticket, {"to_status": "triage"})

    assert response.status_code == 400
    assert response.data["code"] == "invalid_transition"
    assert response.data["detail"] == "Transition is invalid."
    assert set(response.data["fields"]) == {"updated_at"}
    assert response.data["correlation_id"] == CORRELATION_ID


def test_stale_transition_returns_conflict_without_side_effects(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    response = _post(
        actor,
        ticket,
        {
            "to_status": "triage",
            "updated_at": (ticket.updated_at - timedelta(microseconds=1)).isoformat(),
        },
    )

    assert response.status_code == 409
    assert response.data["code"] == "stale_ticket"
    assert set(response.data["fields"]) == {"updated_at"}
    assert response.data["correlation_id"] == CORRELATION_ID
    _assert_no_transition_side_effects(ticket, previous_updated_at)


def test_invalid_transition_returns_canonical_bad_request_without_side_effects(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    response = _post(
        actor,
        ticket,
        {"to_status": "closed", "updated_at": ticket.updated_at.isoformat()},
    )

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid_transition",
        "detail": "Transition is invalid.",
        "fields": {"to_status": ["Select an available transition."]},
        "correlation_id": CORRELATION_ID,
    }
    _assert_no_transition_side_effects(ticket, previous_updated_at)


def test_role_restricted_transition_returns_forbidden_without_side_effects(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-supervisors"
    transition.save(update_fields=["required_role"])

    response = _post(
        actor,
        ticket,
        {"to_status": "triage", "updated_at": ticket.updated_at.isoformat()},
    )

    assert response.status_code == 403
    assert response.data == {
        "code": "ticket_action_forbidden",
        "detail": "You cannot perform this ticket action.",
        "fields": {},
        "correlation_id": CORRELATION_ID,
    }
    _assert_no_transition_side_effects(ticket, previous_updated_at)


def test_realm_role_supervisor_can_execute_a_legacy_role_transition(basic_world):
    actor = _user(["supervisor-operational"])
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_role = "ops-supervisors"
    transition.save(update_fields=["required_role"])

    response = _post(
        actor,
        ticket,
        {"to_status": "triage", "updated_at": ticket.updated_at.isoformat()},
    )

    assert response.status_code == 200
    assert response.data["status_code"] == "triage"


@pytest.mark.parametrize("missing", ["resolution_code", "resolution_summary"])
def test_resolution_transition_requires_code_and_summary(basic_world, missing):
    actor = _supervisor(basic_world, role_key="assistant-master")
    ticket = _ticket(basic_world, status_code="in_progress")
    payload = {
        "to_status": "resolved",
        "updated_at": ticket.updated_at.isoformat(),
        "resolution_code": "INFO_PROVIDED",
        "resolution_summary": "Answer supplied",
    }
    payload[missing] = ""

    response = _post(actor, ticket, payload)

    assert response.status_code == 400
    assert response.data["code"] == "invalid_transition"
    assert missing in response.data["fields"]
    ticket.refresh_from_db()
    assert ticket.status.code == "in_progress"


def test_escalation_transition_rejects_explicit_null_supervisor_at_serializer(
    basic_world,
):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world, status_code="in_progress")
    previous_updated_at = ticket.updated_at

    response = _post(
        actor,
        ticket,
        {
            "to_status": "escalated",
            "updated_at": ticket.updated_at.isoformat(),
            "reason": "Requires delegated approval",
            "supervisor_id": None,
        },
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_transition"
    assert response.data["fields"] == {
        "supervisor_id": ["This field may not be null."]
    }
    ticket.refresh_from_db()
    assert ticket.status.code == "in_progress"
    assert ticket.assignee_id is None
    assert ticket.updated_at == previous_updated_at
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 0
    assert AuditEvent.objects.filter(object_id=str(ticket.id)).count() == 0
    assert ticket.custody_events.count() == 0
    assert OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count() == 0


def test_non_escalation_transition_rejects_explicit_null_supervisor_at_serializer(
    basic_world,
):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world, status_code="in_progress")
    previous_updated_at = ticket.updated_at

    response = _post(
        actor,
        ticket,
        {
            "to_status": "resolved",
            "updated_at": ticket.updated_at.isoformat(),
            "resolution_code": "INFO_PROVIDED",
            "resolution_summary": "Requester received the answer.",
            "supervisor_id": None,
        },
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_transition"
    assert response.data["fields"] == {
        "supervisor_id": ["This field may not be null."]
    }
    ticket.refresh_from_db()
    assert ticket.status.code == "in_progress"
    assert ticket.assignee_id is None
    assert ticket.updated_at == previous_updated_at
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 0
    assert AuditEvent.objects.filter(object_id=str(ticket.id)).count() == 0
    assert ticket.custody_events.count() == 0
    assert OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count() == 0


def test_non_escalation_transition_rejects_supervisor_uuid_at_service_boundary(
    basic_world,
):
    actor = _supervisor(basic_world, role_key="master")
    ticket = _ticket(basic_world, status_code="in_progress")
    previous_updated_at = ticket.updated_at

    response = _post(
        actor,
        ticket,
        {
            "to_status": "resolved",
            "updated_at": ticket.updated_at.isoformat(),
            "resolution_code": "INFO_PROVIDED",
            "resolution_summary": "Requester received the answer.",
            "supervisor_id": str(uuid4()),
        },
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_transition"
    assert response.data["fields"] == {
        "supervisor_id": ["This field is only valid when escalating."]
    }
    ticket.refresh_from_db()
    assert ticket.status.code == "in_progress"
    assert ticket.assignee_id is None
    assert ticket.updated_at == previous_updated_at
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 0
    assert AuditEvent.objects.filter(object_id=str(ticket.id)).count() == 0
    assert ticket.custody_events.count() == 0
    assert OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count() == 0


def test_reason_requirement_and_success_return_refreshed_next_capabilities(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    transition = Transition.objects.get(
        domain=ticket.domain,
        from_status=ticket.status,
        to_status__code="triage",
    )
    transition.required_fields = ["reason"]
    transition.save(update_fields=["required_fields"])

    invalid = _post(
        actor,
        ticket,
        {"to_status": "triage", "updated_at": ticket.updated_at.isoformat()},
    )
    assert invalid.status_code == 400
    assert invalid.data["fields"] == {"reason": ["This field is required."]}

    success = _post(
        actor,
        ticket,
        {
            "to_status": "triage",
            "updated_at": ticket.updated_at.isoformat(),
            "reason": "Initial assessment complete",
        },
    )

    assert success.status_code == 200
    assert success.data["status_code"] == "triage"
    assert success.data["updated_at"] != ticket.updated_at.isoformat()
    assert success.data["available_transition_codes"] == [
        item["to_status"] for item in success.data["available_transitions"]
    ]
    assert "in_progress" in success.data["available_transition_codes"]
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 1
    assert AuditEvent.objects.filter(
        object_id=str(ticket.id), action="ticket.transitioned"
    ).count() == 1
    assert OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id), event_type="ticket.transitioned"
    ).count() == 1


def test_escalation_requires_a_reason_and_records_the_responsible_actor(basic_world):
    actor = _user(["ops-agents"])
    supervisor = _supervisor(basic_world)
    ticket = _ticket(basic_world, status_code="in_progress")

    missing = _post(
        actor,
        ticket,
        {"to_status": "escalated", "updated_at": ticket.updated_at.isoformat()},
    )
    assert missing.status_code == 400
    assert missing.data["fields"] == {
        "reason": ["This field is required."],
        "supervisor_id": ["Select an escalation supervisor."],
    }

    response = _post(
        actor,
        ticket,
        {
            "to_status": "escalated",
            "updated_at": ticket.updated_at.isoformat(),
            "reason": "SLA risk",
            "supervisor_id": str(supervisor.id),
        },
    )

    assert response.status_code == 200
    ticket.refresh_from_db()
    assert ticket.assignee_id == supervisor.id
    event = ticket.custody_events.order_by("sequence").last()
    assert event is not None
    assert event.event_type == "escalated"
    assert event.actor_subject == actor.keycloak_subject
    assert event.occurred_at is not None
    assert event.reason == "SLA risk"
    audit = AuditEvent.objects.get(
        object_id=str(ticket.id), action="ticket.transitioned"
    )
    assert audit.actor_subject == actor.keycloak_subject
    assert audit.occurred_at is not None
