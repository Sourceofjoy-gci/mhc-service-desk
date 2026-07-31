from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils.dateparse import parse_datetime

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.tickets.assignment import assign_ticket
from apps.tickets.models import OutboxEvent, Ticket
from apps.tickets.services import (
    TicketConflictError,
    TicketPermissionError,
    TicketValidationError,
    update_work_state,
)
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _user(groups: list[str], *, active: bool = True) -> User:
    user = User.objects.create(
        username=f"agent-{uuid4().hex}",
        keycloak_subject=f"subject-{uuid4().hex}",
        keycloak_groups=groups,
        is_active=active,
    )
    user._groups = groups
    return user


def _ticket(basic_world, *, domain: str = "operational", assignee=None) -> Ticket:
    service = basic_world["gen_info"] if domain == "operational" else basic_world["it_inc"]
    prefix = "OP" if domain == "operational" else "IT"
    return Ticket.objects.create(
        number=f"{prefix}-202607-{Ticket.objects.count() + 910001:06d}",
        domain=domain,
        title="Work state",
        status=Status.objects.get(domain=domain, code="new"),
        channel="web",
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        assignee=assignee,
    )


def _expected(ticket: Ticket):
    parsed = parse_datetime(ticket.updated_at.isoformat())
    assert parsed is not None
    assert parsed.microsecond == ticket.updated_at.microsecond
    return parsed


def test_unassigned_agent_can_assign_ticket_to_self(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    updated = assign_ticket(
        ticket_id=ticket.id,
        actor=actor,
        assignee_id=actor.id,
        expected_updated_at=_expected(ticket),
    ).ticket

    assert updated.assignee_id == actor.id


def test_agent_cannot_assign_another_user_and_ticket_is_unchanged(basic_world):
    actor = _user(["ops-agents"])
    other = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    with pytest.raises(TicketValidationError) as caught:
        update_work_state(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=_expected(ticket),
            changes={"assignee": other.id, "team": "Operations"},
        )
    assert caught.value.fields == {"changes": ["Unsupported work-state field."]}

    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert ticket.team == ""
    assert ticket.updated_at == previous_updated_at


def test_supervisor_can_assign_eligible_same_domain_user(basic_world):
    supervisor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    updated = assign_ticket(
        ticket_id=ticket.id,
        actor=supervisor,
        assignee_id=target.id,
        expected_updated_at=_expected(ticket),
    ).ticket

    assert updated.assignee_id == target.id


@pytest.mark.parametrize(
    ("groups", "active"),
    [
        (["it-agents"], True),
        (["ops-agents"], False),
        (["auditors"], True),
        (["ops-agents", "auditors"], True),
    ],
)
def test_supervisor_cannot_assign_ineligible_users(basic_world, groups, active):
    supervisor = _user(["ops-supervisors"])
    target = _user(groups, active=active)
    ticket = _ticket(basic_world)

    with pytest.raises(TicketValidationError) as caught:
        assign_ticket(
            ticket_id=ticket.id,
            actor=supervisor,
            assignee_id=target.id,
            expected_updated_at=_expected(ticket),
        )

    assert caught.value.fields == {
        "assignee_id": ["Select an eligible assignee."],
    }
    ticket.refresh_from_db()
    assert ticket.assignee_id is None


def test_agent_updates_planning_fields(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world, assignee=actor)
    next_action_at = parse_datetime("2026-07-28T10:30:00+02:00")

    updated = update_work_state(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=_expected(ticket),
        changes={
            "team": "Operations North",
            "waiting_reason": "requester",
            "blocked_reason": "Awaiting signed documents",
            "next_action": "Call requester",
            "next_action_at": next_action_at,
        },
    )

    assert updated.team == "Operations North"
    assert updated.waiting_reason == "requester"
    assert updated.blocked_reason == "Awaiting signed documents"
    assert updated.next_action == "Call requester"
    assert updated.next_action_at == next_action_at


def test_only_elevated_user_can_change_confidentiality(basic_world):
    agent = _user(["ops-agents"])
    supervisor = _user(["ops-supervisors"])
    ticket = _ticket(basic_world)

    with pytest.raises(TicketPermissionError):
        update_work_state(
            ticket_id=ticket.id,
            actor=agent,
            expected_updated_at=_expected(ticket),
            changes={"confidentiality": "sensitive"},
        )

    ticket.refresh_from_db()
    updated = update_work_state(
        ticket_id=ticket.id,
        actor=supervisor,
        expected_updated_at=_expected(ticket),
        changes={"confidentiality": "sensitive"},
    )
    assert updated.confidentiality == "sensitive"


def test_auditor_cannot_update_work_state(basic_world):
    auditor = _user(["auditors"])
    ticket = _ticket(basic_world)

    with pytest.raises(TicketPermissionError):
        update_work_state(
            ticket_id=ticket.id,
            actor=auditor,
            expected_updated_at=_expected(ticket),
            changes={"team": "Audit"},
        )


def test_persisted_auditor_cannot_update_with_mutable_token_groups(basic_world):
    actor = _user(["ops-supervisors"])
    auditor_role = Role.objects.create(keycloak_role="auditors", name="Auditor")
    UserRole.objects.create(user=actor, role=auditor_role)
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    with pytest.raises(TicketPermissionError):
        update_work_state(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=_expected(ticket),
            changes={"team": "Must not persist"},
        )

    ticket.refresh_from_db()
    assert ticket.team == ""
    assert ticket.updated_at == previous_updated_at
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()


def test_stale_update_returns_current_timestamp_and_changes_nothing(basic_world):
    actor = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    stale = ticket.updated_at.replace(microsecond=max(0, ticket.updated_at.microsecond - 1))
    previous = {
        "team": ticket.team,
        "waiting_reason": ticket.waiting_reason,
        "updated_at": ticket.updated_at,
    }

    with pytest.raises(TicketConflictError) as caught:
        update_work_state(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=stale,
            changes={"team": "New team", "waiting_reason": "requester"},
        )

    assert caught.value.current_updated_at == previous["updated_at"]
    ticket.refresh_from_db()
    assert ticket.team == previous["team"]
    assert ticket.waiting_reason == previous["waiting_reason"]
    assert ticket.updated_at == previous["updated_at"]


def test_success_records_one_matching_changed_field_event_pair(basic_world):
    actor = _user(["ops-supervisors"])
    ticket = _ticket(basic_world)

    update_work_state(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=_expected(ticket),
        changes={
            "team": "Operations",
            "waiting_reason": "requester",
        },
    )

    audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.work_state.changed",
    )
    outbox = OutboxEvent.objects.get(
        aggregate_id=str(ticket.id),
        event_type="ticket.work_state.changed",
    )
    assert audit.payload == outbox.payload
    assert audit.payload["actor"] == actor.keycloak_subject
    assert audit.payload["before"] == {
        "team": "",
        "waiting_reason": "",
    }
    assert audit.payload["after"] == {
        "team": "Operations",
        "waiting_reason": "requester",
    }
