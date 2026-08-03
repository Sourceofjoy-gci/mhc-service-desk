from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from freezegun import freeze_time

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.organisations.models import Office, ServiceLocation
from apps.sla.models import SlaInstance, SlaPolicy
from apps.sla.services import evaluate_open_slas
from apps.tickets import assignment as assignment_service
from apps.tickets import services
from apps.tickets.activity import build_ticket_activity
from apps.tickets.custody import verify_custody_chain
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent
from apps.tickets.services import TicketValidationError

pytestmark = pytest.mark.django_db

PRIMARY_DESIGNATIONS = (
    "master",
    "deputy-master",
    "assistant-master",
    "assistant-accountant",
    "accountant",
    "senior-accountant",
    "principal-accountant",
    "financial-controller",
    "estate-examiner",
    "examiner",
    "records-clerk",
    "records-officer",
    "data-clerk",
)

LEGACY_ROLE_DOMAINS = {
    "agent-operational": Ticket.Domain.OPERATIONAL,
    "ops-agents": Ticket.Domain.OPERATIONAL,
    "supervisor-operational": Ticket.Domain.OPERATIONAL,
    "ops-supervisors": Ticket.Domain.OPERATIONAL,
    "agent-it": Ticket.Domain.IT,
    "it-agents": Ticket.Domain.IT,
    "lead-it": Ticket.Domain.IT,
    "it-leads": Ticket.Domain.IT,
}

SUPPORTED_OWNER_ROLES = (*PRIMARY_DESIGNATIONS, *LEGACY_ROLE_DOMAINS)
GROUP_FALLBACK_ROLES = {"ops-agents", "ops-supervisors", "it-agents", "it-leads"}


def _user(*, groups: list[str] | None = None, label: str) -> User:
    user = User.objects.create(
        username=f"matrix-{uuid4().hex}",
        keycloak_subject=f"matrix-subject-{uuid4().hex}",
        display_name=label,
        keycloak_groups=groups or [],
    )
    user._groups = list(groups or [])
    return user


def _scoped_owner(
    *,
    role_key: str,
    domain: str,
    basic_world,
    label: str,
) -> User:
    if role_key in GROUP_FALLBACK_ROLES:
        return _user(groups=[role_key], label=label)
    user = _user(label=label)
    service = (
        basic_world["gen_info"] if domain == Ticket.Domain.OPERATIONAL else basic_world["it_inc"]
    )
    role, _ = Role.objects.update_or_create(
        keycloak_role=role_key,
        defaults={
            "name": role_key.replace("-", " ").title(),
            "scopes": [
                {
                    "domain": domain,
                    "office": str(basic_world["office"].id),
                    "service": str(service.id),
                }
            ],
        },
    )
    UserRole.objects.create(user=user, role=role, office=basic_world["office"])
    return user


def _evidence_counts(ticket: Ticket) -> tuple[int, int, int]:
    return (
        AuditEvent.objects.filter(object_id=str(ticket.id)).count(),
        OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count(),
        TicketCustodyEvent.objects.filter(ticket=ticket).count(),
    )


def _transition(ticket: Ticket, actor: User, to_status: str) -> Ticket:
    resolving = to_status == "resolved"
    return services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code=to_status,
        reason=f"Move ticket to {to_status}.",
        resolution_code="completed" if resolving else "",
        resolution_summary="Work completed and verified." if resolving else "",
    )


@pytest.mark.parametrize("role_key", SUPPORTED_OWNER_ROLES)
def test_supported_role_has_complete_creation_to_closure_custody_timeline(
    basic_world,
    role_key,
):
    domain = LEGACY_ROLE_DOMAINS.get(role_key, Ticket.Domain.OPERATIONAL)
    service = (
        basic_world["gen_info"] if domain == Ticket.Domain.OPERATIONAL else basic_world["it_inc"]
    )
    owner = _scoped_owner(
        role_key=role_key,
        domain=domain,
        basic_world=basic_world,
        label=f"{role_key} primary owner",
    )
    backup = _scoped_owner(
        role_key=role_key,
        domain=domain,
        basic_world=basic_world,
        label=f"{role_key} backup owner",
    )
    actor = (
        _scoped_owner(
            role_key="master",
            domain=domain,
            basic_world=basic_world,
            label="Matrix Master",
        )
        if domain == Ticket.Domain.OPERATIONAL
        else _user(groups=["it-leads"], label="Matrix IT lead")
    )
    destination = ServiceLocation.objects.create(
        office=basic_world["office"],
        name=f"Matrix destination {role_key}",
    )
    started_at = datetime(2026, 7, 27, 6, 0, tzinfo=UTC)

    with freeze_time(started_at):
        ticket = services.create_ticket(
            domain=domain,
            title=f"Role matrix {role_key}",
            description="Full internal chain of custody",
            requester=basic_world["contact"],
            service=service,
            request_type=service.request_types.get(),
            office=basic_world["office"],
            channel=Ticket.Channel.INTERNAL,
            actor_subject=actor.keycloak_subject,
            actor=actor,
        )
        ticket = assignment_service.assign_ticket(
            ticket_id=ticket.id,
            actor=actor,
            assignee_id=owner.id,
            expected_updated_at=ticket.updated_at,
        ).ticket
        ticket = assignment_service.assign_ticket(
            ticket_id=ticket.id,
            actor=actor,
            assignee_id=backup.id,
            expected_updated_at=ticket.updated_at,
            reason="Transfer to the backup owner.",
        ).ticket
        ticket = assignment_service.assign_ticket(
            ticket_id=ticket.id,
            actor=actor,
            assignee_id=None,
            expected_updated_at=ticket.updated_at,
            reason="Return to the team for redistribution.",
        ).ticket
        ticket = assignment_service.assign_ticket(
            ticket_id=ticket.id,
            actor=actor,
            assignee_id=owner.id,
            expected_updated_at=ticket.updated_at,
        ).ticket
        ticket = assignment_service.route_ticket(
            ticket_id=ticket.id,
            actor=actor,
            queue_id=destination.id,
            assignee_id=owner.id,
            expected_updated_at=ticket.updated_at,
            reason="Move work to the active internal queue.",
        ).ticket

        wrong_owner = _user(
            groups=["it-agents" if domain == Ticket.Domain.OPERATIONAL else "ops-agents"],
            label="Wrong scope owner",
        )
        before_rejections = _evidence_counts(ticket)
        with pytest.raises(TicketValidationError):
            assignment_service.route_ticket(
                ticket_id=ticket.id,
                actor=actor,
                queue_id=destination.id,
                assignee_id=wrong_owner.id,
                expected_updated_at=ticket.updated_at,
                reason="This wrong-scope owner must be rejected.",
            )
        other_office = Office.objects.create(
            region=basic_world["region"],
            code=f"MX-{uuid4().hex[:8]}",
            name="Wrong matrix office",
        )
        wrong_queue = ServiceLocation.objects.create(
            office=other_office,
            name=f"Wrong matrix queue {role_key}",
        )
        with pytest.raises(TicketValidationError):
            assignment_service.route_ticket(
                ticket_id=ticket.id,
                actor=actor,
                queue_id=wrong_queue.id,
                assignee_id=owner.id,
                expected_updated_at=ticket.updated_at,
                reason="This wrong-scope queue must be rejected.",
            )
        assert _evidence_counts(ticket) == before_rejections

        policy = SlaPolicy.objects.get(domain=domain, priority=ticket.priority)
        policy.resolution_minutes = 10
        policy.escalation_percent = 90
        policy.save(update_fields=["resolution_minutes", "escalation_percent"])
        SlaInstance.objects.create(
            ticket=ticket,
            policy=policy,
            kind="resolution",
            state=SlaInstance.State.ACTIVE,
            started_at=started_at,
            due_at=started_at + timedelta(minutes=10),
        )

    with freeze_time(started_at + timedelta(minutes=9)):
        evaluate_open_slas()

    with freeze_time(started_at + timedelta(minutes=10)):
        ticket.refresh_from_db()
        ticket = _transition(ticket, actor, "triage")
        ticket = _transition(ticket, actor, "in_progress")
        if domain == Ticket.Domain.IT:
            ticket = _transition(ticket, actor, "validation")
        ticket = _transition(ticket, actor, "resolved")
        ticket = _transition(ticket, actor, "reopened")
        ticket = _transition(ticket, actor, "in_progress")
        if domain == Ticket.Domain.IT:
            ticket = _transition(ticket, actor, "validation")
        ticket = _transition(ticket, actor, "resolved")
        ticket = _transition(ticket, actor, "closed")

    events = list(ticket.custody_events.order_by("sequence", "id"))
    event_types = [event.event_type for event in events]
    required_in_order = [
        "created",
        "assigned",
        "reassigned",
        "unassigned",
        "queue_changed",
        "escalated",
        "status_changed",
        "reopened",
        "closed",
    ]
    positions = [event_types.index(event_type) for event_type in required_in_order]
    assert positions == sorted(positions)
    assert all(
        previous.occurred_at <= current.occurred_at
        for previous, current in zip(events, events[1:], strict=False)
    )
    assert verify_custody_chain(ticket) is True

    workflow_events = [
        event
        for event in events
        if event.event_type in {"status_changed", "reopened", "closed"}
    ]
    visible_workflow = [
        item
        for item in build_ticket_activity(ticket)
        if item["category"] == "workflow"
    ]
    assert len(visible_workflow) == len(workflow_events)
    assert len({item["id"] for item in visible_workflow}) == len(visible_workflow)
