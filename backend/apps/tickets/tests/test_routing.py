from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import get_authority_snapshot
from apps.organisations.models import Office, ServiceLocation
from apps.tickets import assignment as assignment_service
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent
from apps.tickets.permissions import can_route_ticket, can_unqueue_ticket
from apps.tickets.services import (
    TicketConflictError,
    TicketPermissionError,
    TicketScopeError,
    TicketValidationError,
)
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db

CORRELATION_ID = "routing-api-test-correlation"


def _user(
    groups: list[str] | None = None,
    *,
    display_name: str = "",
    active: bool = True,
) -> User:
    # Operational and IT authority is confined to the officer's office, so
    # every staff actor is based at the seeded ``basic_world`` office.
    user = User.objects.create(
        username=f"routing-{uuid4().hex}",
        keycloak_subject=f"routing-subject-{uuid4().hex}",
        display_name=display_name,
        keycloak_groups=groups or [],
        is_active=active,
        office=Office.objects.get(code="TST-1"),
    )
    user._groups = list(groups or [])
    return user


def _queue(basic_world, name: str, *, active: bool = True, office=None):
    return ServiceLocation.objects.create(
        office=office or basic_world["office"],
        name=f"{name}-{uuid4().hex[:8]}",
        is_active=active,
    )


def _ticket(
    basic_world,
    *,
    queue: ServiceLocation | None = None,
    assignee: User | None = None,
    confidentiality: str = Ticket.Confidentiality.NORMAL,
    domain: str = Ticket.Domain.OPERATIONAL,
) -> Ticket:
    service = (
        basic_world["gen_info"] if domain == Ticket.Domain.OPERATIONAL else basic_world["it_inc"]
    )
    prefix = "OP" if domain == Ticket.Domain.OPERATIONAL else "IT"
    return Ticket.objects.create(
        number=f"{prefix}-202607-{Ticket.objects.count() + 990001:06d}",
        domain=domain,
        title="Guarded ticket routing",
        status=Status.objects.get(domain=domain, code="new"),
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        queue=queue,
        assignee=assignee,
        confidentiality=confidentiality,
    )


def _scope(
    ticket: Ticket,
    *,
    queue: ServiceLocation | None,
    restricted: bool = False,
) -> dict[str, object]:
    return {
        "domain": ticket.domain,
        "office": str(ticket.office_id),
        "service": str(ticket.service_id),
        **({"queue": str(queue.id)} if queue is not None else {}),
        **({"restricted_only": True} if restricted else {}),
    }


def _grant(
    user: User,
    ticket: Ticket,
    *,
    role_key: str,
    queues: tuple[ServiceLocation | None, ...],
) -> UserRole:
    role = Role.objects.create(
        keycloak_role=role_key,
        name=f"{role_key}-{uuid4().hex[:8]}",
        scopes=[_scope(ticket, queue=queue) for queue in queues],
    )
    return UserRole.objects.create(user=user, role=role, office=ticket.office)


def _grant_with_independent_offices(
    user: User,
    ticket: Ticket,
    *,
    role_key: str,
    queue: ServiceLocation | None,
    assignment_office: Office,
    configured_office: Office,
) -> UserRole:
    role = Role.objects.create(
        keycloak_role=role_key,
        name=f"{role_key}-{uuid4().hex[:8]}",
        scopes=[
            {
                **_scope(ticket, queue=queue),
                "office": str(configured_office.id),
            }
        ],
    )
    return UserRole.objects.create(
        user=user,
        role=role,
        office=assignment_office,
    )


def _grant_with_assignment_office_only(
    user: User,
    ticket: Ticket,
    *,
    role_key: str,
    queues: tuple[ServiceLocation | None, ...],
) -> UserRole:
    configured_scopes: list[dict[str, object]] = []
    for queue in queues:
        scope = _scope(ticket, queue=queue)
        scope.pop("office")
        configured_scopes.append(scope)
    role = Role.objects.create(
        keycloak_role=role_key,
        name=f"{role_key}-{uuid4().hex[:8]}",
        scopes=configured_scopes,
    )
    return UserRole.objects.create(
        user=user,
        role=role,
        office=ticket.office,
    )


def _counts(ticket: Ticket) -> tuple[int, int, int]:
    return (
        AuditEvent.objects.filter(object_id=str(ticket.id)).count(),
        OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count(),
        TicketCustodyEvent.objects.filter(ticket=ticket).count(),
    )


def _route(
    ticket: Ticket,
    actor: User,
    *,
    queue_id: UUID | None,
    assignee_id: UUID | None,
    expected_updated_at=None,
    reason: str = "Route work to the correct team.",
):
    return assignment_service.route_ticket(
        ticket_id=ticket.id,
        actor=actor,
        queue_id=queue_id,
        assignee_id=assignee_id,
        expected_updated_at=expected_updated_at or ticket.updated_at,
        reason=reason,
    )


def test_supervisor_routes_ticket_to_active_same_office_queue_with_immutable_receipt(
    basic_world,
    monkeypatch,
):
    occurred_at = datetime(2026, 7, 31, 11, 5, tzinfo=UTC)
    monkeypatch.setattr("apps.tickets.assignment.timezone.now", lambda: occurred_at)
    actor = _user(["ops-supervisors"], display_name="Routing Supervisor")
    destination = _queue(basic_world, "Active destination")
    ticket = _ticket(basic_world)

    result = _route(
        ticket,
        actor,
        queue_id=destination.id,
        assignee_id=None,
    )

    result.ticket.refresh_from_db()
    assert result.ticket.queue_id == destination.id
    assert result.ticket.assignee_id is None
    assert result.receipt.ticket_number == ticket.number
    assert result.receipt.previous_queue is None
    assert result.receipt.new_queue.id == str(destination.id)
    assert result.receipt.new_queue.label == destination.name
    assert result.receipt.previous_assignee is None
    assert result.receipt.new_assignee is None
    assert result.receipt.occurred_at == occurred_at
    assert result.receipt.performed_by.kind == "user"
    with pytest.raises(FrozenInstanceError):
        result.receipt.ticket_number = "changed"  # type: ignore[misc]
    event = TicketCustodyEvent.objects.get(ticket=ticket)
    assert event.event_type == "queue_changed"
    assert event.previous_queue is None
    assert event.new_queue == {"id": str(destination.id), "label": destination.name}
    assert event.source_process == "ticket.routing"
    assert event.occurred_at == occurred_at
    assert _counts(ticket) == (1, 1, 1)


@pytest.mark.parametrize("case", ["inactive", "missing", "cross_office", "out_of_scope"])
def test_invalid_destination_queue_has_no_side_effects(basic_world, case):
    current = _queue(basic_world, "Current destination validation")
    ticket = _ticket(basic_world, queue=current)
    actor = _user(["ops-supervisors"])
    destination_id = uuid4()
    expected_exception: type[Exception] = TicketValidationError
    if case == "inactive":
        destination_id = _queue(basic_world, "Inactive", active=False).id
    elif case == "cross_office":
        other_office = Office.objects.create(
            region=basic_world["region"],
            code=f"ROUTE-{uuid4().hex[:8]}",
            name="Other routing office",
        )
        destination_id = _queue(
            basic_world,
            "Cross office",
            office=other_office,
        ).id
    elif case == "out_of_scope":
        destination = _queue(basic_world, "Out of scope")
        destination_id = destination.id
        actor = _user()
        _grant(
            actor,
            ticket,
            role_key="supervisor-operational",
            queues=(current,),
        )
        expected_exception = TicketPermissionError
    previous_updated_at = ticket.updated_at

    with pytest.raises(expected_exception):
        _route(
            ticket,
            actor,
            queue_id=destination_id,
            assignee_id=None,
        )

    ticket.refresh_from_db()
    assert ticket.queue_id == current.id
    assert ticket.updated_at == previous_updated_at
    assert _counts(ticket) == (0, 0, 0)


@pytest.mark.parametrize(
    "actor_factory",
    [
        lambda: _user(["auditors"]),
        lambda: _user(["ops-supervisors"], active=False),
        lambda: _user(["ops-agents"]),
        lambda: _user(["it-leads"]),
    ],
)
def test_unauthorised_actor_cannot_route(basic_world, actor_factory):
    actor = actor_factory()
    destination = _queue(basic_world, "Denied actor destination")
    ticket = _ticket(basic_world)

    with pytest.raises((TicketPermissionError, TicketScopeError)):
        _route(ticket, actor, queue_id=destination.id, assignee_id=None)

    ticket.refresh_from_db()
    assert ticket.queue_id is None
    assert _counts(ticket) == (0, 0, 0)


@pytest.mark.parametrize(
    ("ticket_domain", "actor_role"),
    [
        (Ticket.Domain.OPERATIONAL, "lead-it"),
        (Ticket.Domain.IT, "supervisor-operational"),
    ],
)
def test_legacy_routing_actor_role_family_cannot_cross_configured_domain(
    basic_world,
    ticket_domain,
    actor_role,
):
    current = _queue(basic_world, f"Cross-domain current {actor_role}")
    destination = _queue(basic_world, f"Cross-domain destination {actor_role}")
    ticket = _ticket(basic_world, queue=current, domain=ticket_domain)
    actor = _user()
    _grant(
        actor,
        ticket,
        role_key=actor_role,
        queues=(current, destination),
    )
    previous_updated_at = ticket.updated_at

    with pytest.raises(TicketPermissionError):
        _route(
            ticket,
            actor,
            queue_id=destination.id,
            assignee_id=None,
        )

    ticket.refresh_from_db()
    assert ticket.queue_id == current.id
    assert ticket.assignee_id is None
    assert ticket.status.code == "new"
    assert ticket.updated_at == previous_updated_at
    assert _counts(ticket) == (0, 0, 0)


def test_restricted_only_functional_actor_cannot_route_ordinary_ticket_via_separate_visibility(
    basic_world,
):
    current = _queue(basic_world, "Restricted-only actor current")
    destination = _queue(basic_world, "Restricted-only actor destination")
    ticket = _ticket(basic_world, queue=current)
    actor = _user()
    restricted_supervisor = Role.objects.create(
        keycloak_role="supervisor-operational",
        name="Restricted-only operational supervisor",
        scopes=[
            _scope(ticket, queue=current, restricted=True),
            _scope(ticket, queue=destination, restricted=True),
        ],
    )
    ordinary_visibility = Role.objects.create(
        keycloak_role="visibility-only",
        name="Ordinary ticket visibility",
        scopes=[
            _scope(ticket, queue=current),
            _scope(ticket, queue=destination),
        ],
    )
    UserRole.objects.create(
        user=actor,
        role=restricted_supervisor,
        office=ticket.office,
    )
    UserRole.objects.create(
        user=actor,
        role=ordinary_visibility,
        office=ticket.office,
    )
    original_updated_at = ticket.updated_at

    with pytest.raises(TicketPermissionError):
        _route(
            ticket,
            actor,
            queue_id=destination.id,
            assignee_id=None,
        )

    ticket.refresh_from_db()
    assert ticket.queue_id == current.id
    assert ticket.assignee_id is None
    assert ticket.status.code == "new"
    assert ticket.updated_at == original_updated_at
    assert _counts(ticket) == (0, 0, 0)


def test_queue_only_routing_requires_existing_owner_to_remain_eligible(basic_world):
    current = _queue(basic_world, "Current owner queue")
    destination = _queue(basic_world, "New owner queue")
    owner = _user(display_name="Queue constrained owner")
    ticket = _ticket(basic_world, queue=current, assignee=owner)
    _grant(owner, ticket, role_key="estate-examiner", queues=(current,))
    actor = _user(["ops-supervisors"])

    with pytest.raises(TicketValidationError) as caught:
        _route(
            ticket,
            actor,
            queue_id=destination.id,
            assignee_id=owner.id,
        )
    assert caught.value.fields == {
        "assignee_id": ["Select an eligible assignee."],
    }
    assert _counts(ticket) == (0, 0, 0)

    result = _route(
        ticket,
        actor,
        queue_id=destination.id,
        assignee_id=None,
        reason="Unassign before changing queue.",
    )
    assert result.ticket.queue_id == destination.id
    assert result.ticket.assignee_id is None


def test_queue_only_routing_succeeds_when_existing_owner_matches_destination(basic_world):
    current = _queue(basic_world, "Eligible current owner queue")
    destination = _queue(basic_world, "Eligible destination owner queue")
    owner = _user(display_name="Destination eligible owner")
    ticket = _ticket(basic_world, queue=current, assignee=owner)
    _grant(
        owner,
        ticket,
        role_key="estate-examiner",
        queues=(current, destination),
    )

    result = _route(
        ticket,
        _user(["ops-supervisors"]),
        queue_id=destination.id,
        assignee_id=owner.id,
    )

    assert result.ticket.queue_id == destination.id
    assert result.ticket.assignee_id == owner.id
    assert [event.event_type for event in ticket.custody_events.all()] == ["queue_changed"]


def test_unqueue_requires_non_queue_scope_and_queue_less_owner_eligibility(basic_world):
    current = _queue(basic_world, "Queue clear current")
    owner = _user(display_name="Queue constrained clear owner")
    ticket = _ticket(basic_world, queue=current, assignee=owner)
    _grant(owner, ticket, role_key="estate-examiner", queues=(current,))
    constrained_actor = _user()
    _grant(
        constrained_actor,
        ticket,
        role_key="supervisor-operational",
        queues=(current,),
    )

    with pytest.raises(TicketPermissionError):
        _route(
            ticket,
            constrained_actor,
            queue_id=None,
            assignee_id=None,
        )
    assert _counts(ticket) == (0, 0, 0)

    actor = _user()
    _grant(
        actor,
        ticket,
        role_key="ops-supervisors",
        queues=(current, None),
    )
    with pytest.raises(TicketValidationError):
        _route(
            ticket,
            actor,
            queue_id=None,
            assignee_id=owner.id,
        )

    result = _route(
        ticket,
        actor,
        queue_id=None,
        assignee_id=None,
        reason="Return the ticket to an unqueued state.",
    )
    assert result.ticket.queue_id is None
    assert result.ticket.assignee_id is None


@pytest.mark.parametrize(
    "mismatch_direction",
    ["assignment_office", "configured_scope_office"],
)
@pytest.mark.parametrize("routing_kind", ["destination", "unqueue"])
def test_persisted_routing_authority_requires_independent_office_matches(
    basic_world,
    mismatch_direction,
    routing_kind,
):
    current = _queue(basic_world, f"Office authority current {routing_kind}")
    destination = _queue(basic_world, f"Office authority target {routing_kind}")
    ticket = _ticket(basic_world, queue=current)
    actor = _user()
    _grant(
        actor,
        ticket,
        role_key="supervisor-operational",
        queues=(current,),
    )
    other_office = Office.objects.create(
        region=basic_world["region"],
        code=f"AUTH-{uuid4().hex[:8]}",
        name="Mismatched routing authority office",
    )
    _grant_with_independent_offices(
        actor,
        ticket,
        role_key="estate-examiner",
        queue=destination if routing_kind == "destination" else None,
        assignment_office=(
            other_office if mismatch_direction == "assignment_office" else ticket.office
        ),
        configured_office=(
            other_office if mismatch_direction == "configured_scope_office" else ticket.office
        ),
    )
    previous_updated_at = ticket.updated_at

    with pytest.raises(TicketPermissionError):
        _route(
            ticket,
            actor,
            queue_id=destination.id if routing_kind == "destination" else None,
            assignee_id=None,
        )

    ticket.refresh_from_db()
    assert ticket.queue_id == current.id
    assert ticket.assignee_id is None
    assert ticket.updated_at == previous_updated_at
    assert _counts(ticket) == (0, 0, 0)


@pytest.mark.parametrize("role_key", ["supervisor-operational", "admin"])
def test_restricted_route_uses_assignment_office_for_unconstrained_configured_scope(
    basic_world,
    role_key,
):
    current = _queue(basic_world, f"Restricted current {role_key}")
    destination = _queue(basic_world, f"Restricted destination {role_key}")
    ticket = _ticket(
        basic_world,
        queue=current,
        confidentiality=Ticket.Confidentiality.RESTRICTED,
    )
    actor = _user(display_name="Restricted Route Supervisor")
    _grant_with_assignment_office_only(
        actor,
        ticket,
        role_key=role_key,
        queues=(current, destination),
    )

    result = _route(
        ticket,
        actor,
        queue_id=destination.id,
        assignee_id=None,
        reason="Route restricted work within the assigned office.",
    )

    ticket.refresh_from_db()
    assert result.ticket.id == ticket.id
    assert ticket.queue_id == destination.id
    assert ticket.assignee_id is None
    assert ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
    assert result.receipt.previous_queue is not None
    assert result.receipt.previous_queue.id == str(current.id)
    assert result.receipt.previous_queue.label == current.name
    assert result.receipt.new_queue is not None
    assert result.receipt.new_queue.id == str(destination.id)
    assert result.receipt.new_queue.label == destination.name
    event = TicketCustodyEvent.objects.get(ticket=ticket)
    assert event.event_type == "queue_changed"
    assert event.previous_queue == {
        "id": str(current.id),
        "label": current.name,
    }
    assert event.new_queue == {
        "id": str(destination.id),
        "label": destination.name,
    }
    assert event.reason == "Route restricted work within the assigned office."
    assert event.actor_subject == actor.keycloak_subject
    assert event.source_process == "ticket.routing"
    assert _counts(ticket) == (1, 1, 1)


@pytest.mark.parametrize("role_key", ["supervisor-operational", "admin"])
def test_restricted_unqueue_uses_assignment_office_for_unconstrained_configured_scope(
    basic_world,
    role_key,
):
    current = _queue(basic_world, f"Restricted unqueue current {role_key}")
    ticket = _ticket(
        basic_world,
        queue=current,
        confidentiality=Ticket.Confidentiality.RESTRICTED,
    )
    actor = _user(display_name="Restricted Unqueue Supervisor")
    _grant_with_assignment_office_only(
        actor,
        ticket,
        role_key=role_key,
        queues=(current, None),
    )

    result = _route(
        ticket,
        actor,
        queue_id=None,
        assignee_id=None,
        reason="Return restricted work to its office intake.",
    )

    ticket.refresh_from_db()
    assert result.ticket.id == ticket.id
    assert ticket.queue_id is None
    assert ticket.assignee_id is None
    assert ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
    assert result.receipt.previous_queue is not None
    assert result.receipt.previous_queue.id == str(current.id)
    assert result.receipt.previous_queue.label == current.name
    assert result.receipt.new_queue is None
    event = TicketCustodyEvent.objects.get(ticket=ticket)
    assert event.event_type == "queue_changed"
    assert event.previous_queue == {
        "id": str(current.id),
        "label": current.name,
    }
    assert event.new_queue is None
    assert event.reason == "Return restricted work to its office intake."
    assert event.actor_subject == actor.keycloak_subject
    assert event.source_process == "ticket.routing"
    assert _counts(ticket) == (1, 1, 1)


def test_queue_clear_keeps_owner_when_owner_has_queue_less_scope(basic_world):
    current = _queue(basic_world, "Queue-less eligible current")
    owner = _user(display_name="Queue-less eligible owner")
    ticket = _ticket(basic_world, queue=current, assignee=owner)
    _grant(owner, ticket, role_key="estate-examiner", queues=(current, None))
    actor = _user(["ops-supervisors"])

    result = _route(
        ticket,
        actor,
        queue_id=None,
        assignee_id=owner.id,
    )

    assert result.ticket.queue_id is None
    assert result.ticket.assignee_id == owner.id


@pytest.mark.parametrize("owner_change", ["assigned", "reassigned", "unassigned"])
def test_paired_routing_records_queue_then_owner_with_one_timestamp_and_audit(
    basic_world,
    owner_change,
    monkeypatch,
):
    occurred_at = datetime(2026, 7, 31, 13, 30, tzinfo=UTC)
    monkeypatch.setattr("apps.tickets.assignment.timezone.now", lambda: occurred_at)
    current = _queue(basic_world, f"Pair current {owner_change}")
    destination = _queue(basic_world, f"Pair destination {owner_change}")
    previous = (
        None
        if owner_change == "assigned"
        else _user(
            ["ops-agents"],
            display_name="Previous Pair Owner",
        )
    )
    target = (
        None
        if owner_change == "unassigned"
        else _user(
            ["ops-agents"],
            display_name="New Pair Owner",
        )
    )
    ticket = _ticket(basic_world, queue=current, assignee=previous)

    result = _route(
        ticket,
        _user(["ops-supervisors"], display_name="Pair Supervisor"),
        queue_id=destination.id,
        assignee_id=target.id if target else None,
        reason="Paired owner and queue change.",
    )

    events = list(ticket.custody_events.order_by("sequence"))
    assert [event.event_type for event in events] == ["queue_changed", owner_change]
    assert events[0].occurred_at == events[1].occurred_at == occurred_at
    assert {event.source_process for event in events} == {"ticket.routing"}
    audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.routing.changed",
    )
    assert {event.source_record_id for event in events} == {str(audit.id)}
    assert {event.source_record_type for event in events} == {"audit_event"}
    assert events[0].previous_queue == {
        "id": str(current.id),
        "label": current.name,
    }
    assert events[0].new_queue == {
        "id": str(destination.id),
        "label": destination.name,
    }
    assert result.receipt.occurred_at == occurred_at
    if target:
        assert events[1].new_owner["id"] == str(target.id)
        assert events[1].new_designations == ["Operational Agent"]
        assert events[1].new_team_labels == ["Operational"]
    if previous:
        assert events[1].previous_owner["id"] == str(previous.id)


def test_unchanged_routing_is_invalid_without_side_effects(basic_world):
    queue = _queue(basic_world, "Unchanged queue")
    owner = _user(["ops-agents"])
    ticket = _ticket(basic_world, queue=queue, assignee=owner)
    previous_updated_at = ticket.updated_at

    with pytest.raises(TicketValidationError) as caught:
        _route(
            ticket,
            _user(["ops-supervisors"]),
            queue_id=queue.id,
            assignee_id=owner.id,
        )

    assert caught.value.fields == {
        "routing": ["Queue and assignee must change."],
    }
    ticket.refresh_from_db()
    assert ticket.updated_at == previous_updated_at
    assert _counts(ticket) == (0, 0, 0)


def test_stale_routing_has_one_winner_and_canonical_conflict(basic_world):
    first = _queue(basic_world, "First winner queue")
    second = _queue(basic_world, "Second stale queue")
    ticket = _ticket(basic_world)
    actor = _user(["ops-supervisors"])
    original_updated_at = ticket.updated_at

    winner = _route(
        ticket,
        actor,
        queue_id=first.id,
        assignee_id=None,
        expected_updated_at=original_updated_at,
    )
    with pytest.raises(TicketConflictError) as caught:
        _route(
            ticket,
            actor,
            queue_id=second.id,
            assignee_id=None,
            expected_updated_at=original_updated_at,
        )

    assert caught.value.current_updated_at == winner.ticket.updated_at
    ticket.refresh_from_db()
    assert ticket.queue_id == first.id
    assert _counts(ticket) == (1, 1, 1)


@pytest.mark.parametrize("failure_boundary", ["audit", "outbox", "custody"])
def test_routing_rolls_back_queue_and_owner_on_evidence_failure(
    basic_world,
    failure_boundary,
    monkeypatch,
):
    current = _queue(basic_world, f"Rollback current {failure_boundary}")
    destination = _queue(basic_world, f"Rollback destination {failure_boundary}")
    previous = _user(["ops-agents"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world, queue=current, assignee=previous)
    previous_updated_at = ticket.updated_at

    def fail(**kwargs):
        raise RuntimeError(f"{failure_boundary} unavailable")

    manager = {
        "audit": AuditEvent.objects,
        "outbox": OutboxEvent.objects,
        "custody": TicketCustodyEvent.objects,
    }[failure_boundary]
    monkeypatch.setattr(manager, "create", fail)

    with pytest.raises(RuntimeError, match=f"{failure_boundary} unavailable"):
        _route(
            ticket,
            _user(["ops-supervisors"]),
            queue_id=destination.id,
            assignee_id=target.id,
        )

    ticket.refresh_from_db()
    assert ticket.queue_id == current.id
    assert ticket.assignee_id == previous.id
    assert ticket.updated_at == previous_updated_at
    assert _counts(ticket) == (0, 0, 0)


def test_system_routing_requires_named_process_and_revalidates_owner(basic_world):
    destination = _queue(basic_world, "System destination")
    ineligible = _user(["it-agents"])
    ticket = _ticket(basic_world)
    kwargs = {
        "ticket_id": ticket.id,
        "queue_id": destination.id,
        "assignee_id": ineligible.id,
        "actor_subject": "automation:route-1",
        "actor_display_name": "Automation route",
        "source_process": "automation.route",
        "reason": "Rule selected route.",
    }

    with pytest.raises(TicketValidationError):
        assignment_service.route_ticket_by_system(**kwargs)
    assert _counts(ticket) == (0, 0, 0)

    target = _user(["ops-agents"], display_name="System routed owner")
    kwargs["assignee_id"] = target.id
    result = assignment_service.route_ticket_by_system(**kwargs)
    assert result.ticket.queue_id == destination.id
    assert result.ticket.assignee_id == target.id
    events = list(ticket.custody_events.order_by("sequence"))
    assert [event.event_type for event in events] == ["queue_changed", "assigned"]
    assert {event.actor_kind for event in events} == {"system"}
    assert {event.actor_subject for event in events} == {"automation:route-1"}


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _routing_url(ticket: Ticket) -> str:
    return reverse("tickets-routing", args=[ticket.number])


def _post_routing(
    ticket: Ticket,
    actor: User,
    *,
    queue_id: UUID | None,
    assignee_id: UUID | None,
    updated_at=None,
):
    return _client(actor).post(
        _routing_url(ticket),
        {
            "queue_id": str(queue_id) if queue_id else None,
            "assignee_id": str(assignee_id) if assignee_id else None,
            "updated_at": (updated_at or ticket.updated_at).isoformat(),
            "reason": "Route through the staff API.",
        },
        format="json",
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )


def test_routing_api_returns_refreshed_ticket_and_only_immutable_receipt(basic_world):
    destination = _queue(basic_world, "API destination")
    target = _user(["ops-agents"], display_name="API routed owner")
    ticket = _ticket(basic_world)

    response = _post_routing(
        ticket,
        _user(["ops-supervisors"], display_name="API route supervisor"),
        queue_id=destination.id,
        assignee_id=target.id,
    )

    assert response.status_code == 200
    assert set(response.data) == {"ticket", "receipt"}
    assert response.data["ticket"]["number"] == ticket.number
    assert response.data["ticket"]["assignee"] == target.id
    assert response.data["receipt"]["previous_queue"] is None
    assert response.data["receipt"]["new_queue"] == {
        "id": str(destination.id),
        "label": destination.name,
    }
    assert response.data["receipt"]["new_assignee"]["id"] == str(target.id)
    event = ticket.custody_events.order_by("sequence").first()
    assert parse_datetime(response.data["receipt"]["occurred_at"]) == event.occurred_at


def test_routing_api_maps_unchanged_pair_to_invalid_routing(basic_world):
    queue = _queue(basic_world, "API unchanged")
    owner = _user(["ops-agents"])
    ticket = _ticket(basic_world, queue=queue, assignee=owner)

    response = _post_routing(
        ticket,
        _user(["ops-supervisors"]),
        queue_id=queue.id,
        assignee_id=owner.id,
    )

    assert response.status_code == 400
    assert response.data == {
        "code": "invalid_routing",
        "detail": "Routing is invalid.",
        "fields": {"routing": ["Queue and assignee must change."]},
        "correlation_id": CORRELATION_ID,
    }
    assert _counts(ticket) == (0, 0, 0)


def test_routing_api_maps_updated_at_to_conflict_and_enforces_scope(basic_world):
    destination = _queue(basic_world, "API stale destination")
    ticket = _ticket(basic_world)
    stale = ticket.updated_at - timedelta(microseconds=1)

    stale_response = _post_routing(
        ticket,
        _user(["ops-supervisors"]),
        queue_id=destination.id,
        assignee_id=None,
        updated_at=stale,
    )
    assert stale_response.status_code == 409
    assert stale_response.data["code"] == "stale_ticket"
    assert parse_datetime(stale_response.data["fields"]["updated_at"][0]) == ticket.updated_at

    hidden_response = _post_routing(
        ticket,
        _user(["it-leads"]),
        queue_id=destination.id,
        assignee_id=None,
    )
    assert hidden_response.status_code == 404
    assert _counts(ticket) == (0, 0, 0)


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"queue_id": None, "assignee_id": None, "reason": "x"}, "updated_at"),
        (
            {
                "queue_id": "not-a-uuid",
                "assignee_id": None,
                "updated_at": "2026-07-31T12:00:00Z",
                "reason": "x",
            },
            "queue_id",
        ),
        (
            {
                "queue_id": None,
                "assignee_id": None,
                "updated_at": "2026-07-31T12:00:00Z",
                "reason": " ",
            },
            "reason",
        ),
    ],
)
def test_routing_api_validates_required_fields(basic_world, payload, field):
    ticket = _ticket(basic_world)
    response = _client(_user(["ops-supervisors"])).post(
        _routing_url(ticket),
        payload,
        format="json",
        HTTP_X_CORRELATION_ID=CORRELATION_ID,
    )

    assert response.status_code == 400
    assert response.data["code"] == "invalid_routing"
    assert field in response.data["fields"]
    assert _counts(ticket) == (0, 0, 0)


def _grant_with_keycloak_office_only(user: User, *, role_key: str) -> UserRole:
    """Grant a role the way offices are sourced now: from Keycloak, not from the
    ``UserRole`` row, so the assignment itself carries no office at all."""
    role = Role.objects.create(
        keycloak_role=role_key,
        name=f"{role_key}-{uuid4().hex[:8]}",
    )
    return UserRole.objects.create(user=user, role=role, office=None)


@pytest.mark.parametrize("routing_kind", ["destination", "unqueue"])
def test_office_less_persisted_supervisor_routes_restricted_work_of_own_office(
    basic_world,
    routing_kind,
):
    """Confinement rewrites the snapshot's scopes, and routing reads its
    restricted-visibility key off the role grant. Leaving the grant unconfined
    made that lookup miss, locking a supervisor out of their own office's
    restricted work — precisely the configuration Keycloak-sourced offices
    produce, because those ``UserRole`` rows carry no office."""
    current = _queue(basic_world, f"Office-less supervisor current {routing_kind}")
    destination = _queue(basic_world, f"Office-less supervisor target {routing_kind}")
    ticket = _ticket(
        basic_world,
        queue=current,
        confidentiality=Ticket.Confidentiality.RESTRICTED,
    )
    actor = _user(display_name="Office-less Supervisor")
    assignment = _grant_with_keycloak_office_only(actor, role_key="ops-supervisors")
    assert assignment.office_id is None
    assert actor.office_id == ticket.office_id

    result = _route(
        ticket,
        actor,
        queue_id=destination.id if routing_kind == "destination" else None,
        assignee_id=None,
        reason="Route restricted work inside my own office.",
    )

    ticket.refresh_from_db()
    assert result.ticket.id == ticket.id
    assert ticket.queue_id == (destination.id if routing_kind == "destination" else None)
    assert ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
    assert _counts(ticket) == (1, 1, 1)


def test_office_less_persisted_supervisor_cannot_route_another_office(basic_world):
    """The same grant must not become a national one: confinement binds it to
    the officer's own office, not to every office."""
    other_office = Office.objects.create(
        region=basic_world["region"],
        code=f"OTHER-{uuid4().hex[:8]}",
        name="Another office entirely",
    )
    current = _queue(basic_world, "Foreign current", office=other_office)
    destination = _queue(basic_world, "Foreign target", office=other_office)
    ticket = _ticket(basic_world, queue=current)
    Ticket.objects.filter(pk=ticket.pk).update(office=other_office)
    ticket.refresh_from_db()
    actor = _user(display_name="Office-less Supervisor Abroad")
    _grant_with_keycloak_office_only(actor, role_key="ops-supervisors")

    # The confined snapshot does not even make the foreign ticket visible, so
    # the denial lands one step earlier than a permission refusal.
    with pytest.raises(TicketScopeError):
        _route(ticket, actor, queue_id=destination.id, assignee_id=None)

    ticket.refresh_from_db()
    assert ticket.queue_id == current.id
    assert _counts(ticket) == (0, 0, 0)


@pytest.mark.parametrize("routing_kind", ["destination", "unqueue"])
def test_office_less_persisted_supervisor_with_desk_role_routes_own_restricted_work(
    basic_world,
    routing_kind,
):
    """A combined desk/supervisor identity keeps its supervisor half intact.

    Holding a service desk role makes the whole identity cross-office, and the
    national reach that grants comes from one appended unconfined operational
    scope -- not from the role grants. Exempting the grants from confinement as
    well left them carrying no office at all, so routing's restricted-visibility
    lookup missed the office-keyed entry that confinement had just written and
    denied a supervisor the restricted work of their own office: the very
    lockout already fixed for identities without a desk role.
    """
    current = _queue(basic_world, f"Desk supervisor current {routing_kind}")
    destination = _queue(basic_world, f"Desk supervisor target {routing_kind}")
    ticket = _ticket(
        basic_world,
        queue=current,
        confidentiality=Ticket.Confidentiality.RESTRICTED,
    )
    actor = _user(display_name="Desk Supervisor")
    supervision = _grant_with_keycloak_office_only(actor, role_key="ops-supervisors")
    desk = _grant_with_keycloak_office_only(actor, role_key="service-desk-agents")
    assert supervision.office_id is None
    assert desk.office_id is None
    assert actor.office_id == ticket.office_id
    # Without the desk half this is the plain office-less supervisor case, so
    # pin that the cross-office branch is the one under test.
    assert get_authority_snapshot(actor).cross_office_identity is True

    result = _route(
        ticket,
        actor,
        queue_id=destination.id if routing_kind == "destination" else None,
        assignee_id=None,
        reason="Route my own office's restricted work while also on the desk.",
    )

    ticket.refresh_from_db()
    assert result.ticket.id == ticket.id
    assert ticket.queue_id == (destination.id if routing_kind == "destination" else None)
    assert ticket.confidentiality == Ticket.Confidentiality.RESTRICTED
    assert _counts(ticket) == (1, 1, 1)


def test_grant_bound_to_another_office_is_inert_in_both_offices(basic_world):
    """Confinement rewrites a foreign-office grant instead of dropping it.

    A grant issued for another office is deliberately kept rather than discarded,
    on the argument that confinement leaves it unable to match anything. Pin both
    halves of that argument. The grant's scopes arrive carrying no office of their
    own, so confinement rewrites them to the officer's office while the issued
    office stays on the grant itself; every consumer requires the grant's office
    and its scope's office to *both* equal the ticket's, so the survivor is inert
    in the officer's office (the grant's office disagrees) and equally inert in
    the office it names (the rewritten scope disagrees).

    The shape assertions are the guard here: with no scope surviving in either
    office this actor's routing denial is carried by confinement of the snapshot
    scopes, so the behavioural half alone would still pass if grant confinement
    were removed -- exactly the weakness of
    ``test_office_less_persisted_supervisor_cannot_route_another_office``.
    """
    issued_office = Office.objects.create(
        region=basic_world["region"],
        code=f"ISSUED-{uuid4().hex[:8]}",
        name="Office the grant was issued for",
    )
    home_queue = _queue(basic_world, "Home destination")
    issued_queue = _queue(basic_world, "Issued destination", office=issued_office)

    actor = _user(display_name="Supervisor Granted Elsewhere")
    assert actor.office_id == basic_world["office"].id
    role = Role.objects.create(
        keycloak_role="ops-supervisors",
        name=f"ops-supervisors-{uuid4().hex[:8]}",
    )
    assignment = UserRole.objects.create(user=actor, role=role, office=issued_office)
    assert assignment.office_id == issued_office.id

    home_ticket = _ticket(basic_world, queue=_queue(basic_world, "Home current"))
    issued_ticket = _ticket(basic_world, queue=issued_queue)
    Ticket.objects.filter(pk=issued_ticket.pk).update(office=issued_office)
    issued_ticket.refresh_from_db()
    assert home_ticket.office_id == basic_world["office"].id
    assert issued_ticket.office_id == issued_office.id

    snapshot = get_authority_snapshot(actor)
    # Kept, not dropped -- and confined: the issued office stays on the grant
    # while its scope is rewritten to the officer's own office.
    assert [grant.role_key for grant in snapshot.role_grants] == ["ops-supervisors"]
    survivor = snapshot.role_grants[0]
    assert survivor.office_id == issued_office.id
    assert [scope.office_id for scope in survivor.scopes] == [str(basic_world["office"].id)]
    # The officer's own scopes were confined away entirely, so the grant is the
    # only authority left standing and it matches no office at all.
    assert snapshot.scopes == ()

    # At the officer's own office the grant's issued office rules it out.
    assert can_route_ticket(actor, home_ticket, home_queue) is False
    assert can_unqueue_ticket(actor, home_ticket) is False
    # At the office the grant names, its confined scope rules it out.
    assert can_route_ticket(actor, issued_ticket, issued_queue) is False
    assert can_unqueue_ticket(actor, issued_ticket) is False
