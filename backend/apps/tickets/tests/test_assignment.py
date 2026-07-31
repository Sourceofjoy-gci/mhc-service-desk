from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from uuid import UUID, uuid4

import pytest
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity_access.authority_lock import lock_user_authorities
from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import get_authority_snapshot
from apps.tickets import assignment as assignment_service
from apps.tickets.assignment import (
    AssignmentActor,
    AssignmentParty,
    assign_ticket,
    assign_ticket_by_system,
)
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent
from apps.tickets.services import (
    TicketConflictError,
    TicketPermissionError,
    TicketScopeError,
    TicketValidationError,
)
from apps.workflow.models import Status, TransitionHistory

pytestmark = pytest.mark.django_db


def _user(
    groups: list[str] | None = None,
    *,
    display_name: str = "",
    active: bool = True,
) -> User:
    username = f"staff-{uuid4().hex}"
    user = User.objects.create(
        username=username,
        keycloak_subject=f"subject-{uuid4().hex}",
        display_name=display_name,
        keycloak_groups=groups or [],
        is_active=active,
    )
    user._groups = list(groups or [])
    return user


def _ticket(
    basic_world,
    *,
    assignee: User | None = None,
    status: str = "new",
    domain: str = Ticket.Domain.OPERATIONAL,
) -> Ticket:
    service = (
        basic_world["gen_info"] if domain == Ticket.Domain.OPERATIONAL else basic_world["it_inc"]
    )
    return Ticket.objects.create(
        number=f"{domain[:2].upper()}-202607-{Ticket.objects.count() + 930001:06d}",
        domain=domain,
        title="Assignment service",
        status=Status.objects.get(domain=domain, code=status),
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        assignee=assignee,
    )


def _assignment_rows(ticket: Ticket) -> tuple[int, int, int]:
    return (
        AuditEvent.objects.filter(
            object_id=str(ticket.id),
            action="ticket.assignment.changed",
        ).count(),
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id),
            event_type="ticket.assignment.changed",
        ).count(),
        TicketCustodyEvent.objects.filter(ticket=ticket).count(),
    )


def _assign(
    ticket: Ticket,
    actor: User,
    assignee_id: UUID | None,
    *,
    reason: str = "",
):
    return assign_ticket(
        ticket_id=ticket.id,
        actor=actor,
        assignee_id=assignee_id,
        expected_updated_at=ticket.updated_at,
        reason=reason,
    )


def test_initial_assignment_records_one_atomic_event_and_complete_receipt(
    basic_world,
    monkeypatch,
):
    occurred_at = datetime(2026, 7, 31, 8, 15, 30, 123456, tzinfo=UTC)
    monkeypatch.setattr("apps.tickets.assignment.timezone.now", lambda: occurred_at)
    actor = _user(["ops-supervisors"], display_name="Assigning Supervisor")
    target = _user(["ops-agents"], display_name="Estate Officer")
    ticket = _ticket(basic_world)

    result = _assign(ticket, actor, target.id)

    event = TicketCustodyEvent.objects.get(ticket=ticket)
    assert result.changed is True
    assert result.ticket.assignee_id == target.id
    assert result.receipt.ticket_number == ticket.number
    assert result.receipt.action == "assigned"
    assert result.receipt.previous_assignee is None
    assert result.receipt.new_assignee == AssignmentParty(
        id=str(target.id),
        display_name="Estate Officer",
        designations=("Operational Agent",),
        team_labels=("Operational",),
    )
    assert result.receipt.occurred_at == occurred_at == event.occurred_at
    assert result.receipt.performed_by == AssignmentActor(
        kind="user",
        subject=actor.keycloak_subject,
        display_name="Assigning Supervisor",
    )
    assert event.event_type == "assigned"
    assert event.source_process == "ticket.assignment"
    assert event.actor_kind == "user"
    assert event.actor_subject == actor.keycloak_subject
    assert event.actor_display_name == "Assigning Supervisor"
    assert event.previous_owner is None
    assert event.new_owner == {
        "id": str(target.id),
        "subject": target.keycloak_subject,
        "display_name": "Estate Officer",
    }
    assert event.new_designations == ["Operational Agent"]
    assert event.new_team_labels == ["Operational"]
    assert _assignment_rows(ticket) == (1, 1, 1)


def test_reassignment_snapshots_both_parties_and_requires_reason(basic_world):
    actor = _user(["ops-supervisors"], display_name="Supervisor")
    previous = _user(["ops-agents"], display_name="Previous Owner")
    target = _user(["ops-agents"], display_name="New Owner")
    ticket = _ticket(basic_world, assignee=previous)

    with pytest.raises(TicketValidationError) as missing:
        _assign(ticket, actor, target.id, reason="  ")
    assert missing.value.fields == {"reason": ["This field is required."]}

    result = _assign(ticket, actor, target.id, reason="Balance the caseload")

    event = TicketCustodyEvent.objects.get(ticket=ticket)
    assert result.receipt.action == "reassigned"
    assert result.receipt.previous_assignee == AssignmentParty(
        id=str(previous.id),
        display_name="Previous Owner",
        designations=("Operational Agent",),
        team_labels=("Operational",),
    )
    assert result.receipt.new_assignee == AssignmentParty(
        id=str(target.id),
        display_name="New Owner",
        designations=("Operational Agent",),
        team_labels=("Operational",),
    )
    assert event.event_type == "reassigned"
    assert event.reason == "Balance the caseload"
    assert event.previous_owner is not None
    assert event.previous_owner["id"] == str(previous.id)
    assert event.new_owner is not None
    assert event.new_owner["id"] == str(target.id)


def test_unassignment_records_previous_party_and_requires_reason(basic_world):
    actor = _user(["ops-supervisors"])
    previous = _user(["ops-agents"], display_name="Current Owner")
    ticket = _ticket(basic_world, assignee=previous)

    with pytest.raises(TicketValidationError) as missing:
        _assign(ticket, actor, None)
    assert missing.value.fields == {"reason": ["This field is required."]}

    result = _assign(ticket, actor, None, reason="Return to team queue")

    event = TicketCustodyEvent.objects.get(ticket=ticket)
    assert result.changed is True
    assert result.ticket.assignee_id is None
    assert result.receipt.action == "unassigned"
    assert result.receipt.previous_assignee is not None
    assert result.receipt.previous_assignee.id == str(previous.id)
    assert result.receipt.new_assignee is None
    assert event.event_type == "unassigned"
    assert event.new_owner is None


def test_same_owner_is_a_successful_noop_without_side_effects(
    basic_world,
    monkeypatch,
):
    occurred_at = datetime(2026, 7, 31, 9, 0, tzinfo=UTC)
    monkeypatch.setattr("apps.tickets.assignment.timezone.now", lambda: occurred_at)
    actor = _user(["ops-supervisors"], display_name="Supervisor")
    owner = _user(["ops-agents"], display_name="Unchanged Owner")
    ticket = _ticket(basic_world, assignee=owner)
    previous_updated_at = ticket.updated_at

    result = _assign(ticket, actor, owner.id)

    unchanged_party = AssignmentParty(
        id=str(owner.id),
        display_name="Unchanged Owner",
        designations=("Operational Agent",),
        team_labels=("Operational",),
    )
    assert result.changed is False
    assert result.receipt.action == "unchanged"
    assert result.receipt.previous_assignee == unchanged_party
    assert result.receipt.new_assignee == unchanged_party
    assert result.receipt.occurred_at == occurred_at
    assert result.ticket.updated_at == previous_updated_at
    assert _assignment_rows(ticket) == (0, 0, 0)


def test_stale_timestamp_conflicts_before_any_mutation(basic_world):
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    stale = ticket.updated_at - timedelta(microseconds=1)

    with pytest.raises(TicketConflictError) as caught:
        assign_ticket(
            ticket_id=ticket.id,
            actor=actor,
            assignee_id=target.id,
            expected_updated_at=stale,
        )

    assert caught.value.current_updated_at == ticket.updated_at
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


def test_actor_without_assignment_authority_cannot_assign_another_user(basic_world):
    actor = _user(["ops-agents"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    with pytest.raises(TicketPermissionError):
        _assign(ticket, actor, target.id)

    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


def test_eligible_self_assignment_is_the_only_non_assigner_exception(basic_world):
    eligible_actor = _user(["ops-agents"], display_name="Self Assignee")
    ticket = _ticket(basic_world)

    result = _assign(ticket, eligible_actor, eligible_actor.id)

    assert result.changed is True
    assert result.ticket.assignee_id == eligible_actor.id

    ineligible_actor = _user(["ops-agents", "auditors"])
    other_ticket = _ticket(basic_world)
    with pytest.raises(TicketPermissionError):
        _assign(other_ticket, ineligible_actor, ineligible_actor.id)
    other_ticket.refresh_from_db()
    assert other_ticket.assignee_id is None


@pytest.mark.parametrize("target_kind", ["inactive", "expired", "scope_mismatch"])
def test_ineligible_target_is_rejected_with_stable_field_error(
    basic_world,
    target_kind,
):
    actor = _user(["ops-supervisors"])
    ticket = _ticket(basic_world)
    if target_kind == "inactive":
        target = _user(["ops-agents"], active=False)
    elif target_kind == "scope_mismatch":
        target = _user(["it-agents"])
    else:
        target = _user()
        role = Role.objects.create(
            keycloak_role="estate-examiner",
            name="Estate Examiner",
            scopes=[{"domain": "operational"}],
        )
        UserRole.objects.create(
            user=target,
            role=role,
            expires_at=timezone.now() - timedelta(seconds=1),
        )

    with pytest.raises(TicketValidationError) as caught:
        _assign(ticket, actor, target.id)

    assert caught.value.fields == {
        "assignee_id": ["Select an eligible assignee."],
    }
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


def test_supplied_authority_snapshot_cannot_bypass_locked_actor_revalidation(
    basic_world,
):
    actor = _user()
    actor._groups = ["ops-supervisors"]
    snapshot = get_authority_snapshot(actor)
    actor._groups = []
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    with pytest.raises(TicketScopeError):
        assign_ticket(
            ticket_id=ticket.id,
            actor=actor,
            assignee_id=target.id,
            expected_updated_at=ticket.updated_at,
            snapshot=snapshot,
        )

    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


def test_target_is_revalidated_after_ticket_lock(basic_world, monkeypatch):
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    original = assignment_service.eligible_assignee_candidate

    def deactivate_target_during_revalidation(locked_ticket, user, *, snapshot):
        if user.pk == target.pk:
            User.objects.filter(pk=target.pk).update(is_active=False)
            user.is_active = False
        return original(locked_ticket, user, snapshot=snapshot)

    monkeypatch.setattr(
        assignment_service,
        "eligible_assignee_candidate",
        deactivate_target_during_revalidation,
    )

    with pytest.raises(TicketValidationError) as caught:
        _assign(ticket, actor, target.id)

    assert caught.value.fields == {
        "assignee_id": ["Select an eligible assignee."],
    }
    ticket.refresh_from_db()
    assert ticket.assignee_id is None


def test_assignment_and_automatic_status_transition_are_distinct_chronological_events(
    basic_world,
):
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world, status="triage")

    result = _assign(ticket, actor, target.id)

    result.ticket.refresh_from_db()
    events = list(TicketCustodyEvent.objects.filter(ticket=ticket))
    history = TransitionHistory.objects.get(ticket=ticket)
    assert result.ticket.status.code == "assigned"
    assert history.from_status.code == "triage"
    assert history.to_status.code == "assigned"
    assert [event.event_type for event in events] == ["assigned", "status_changed"]
    assert events[0].previous_status is None
    assert events[0].new_status is None
    assert events[1].previous_status == {"code": "triage", "label": "Triage"}
    assert events[1].new_status == {"code": "assigned", "label": "Assigned"}
    assert events[0].occurred_at <= events[1].occurred_at
    assert _assignment_rows(ticket) == (1, 1, 2)
    assert AuditEvent.objects.filter(object_id=str(ticket.id)).count() == 2
    assert OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count() == 2


def test_custody_failure_rolls_back_ticket_transition_audit_and_outbox(
    basic_world,
    monkeypatch,
):
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world, status="triage")
    previous_updated_at = ticket.updated_at
    monkeypatch.setattr(
        TicketCustodyEvent.objects,
        "create",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("custody unavailable")),
    )

    with pytest.raises(RuntimeError, match="custody unavailable"):
        _assign(ticket, actor, target.id)

    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert ticket.status.code == "triage"
    assert ticket.updated_at == previous_updated_at
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 0
    assert _assignment_rows(ticket) == (0, 0, 0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor_subject", "  "),
        ("actor_display_name", ""),
        ("source_process", "\t"),
        ("reason", " "),
    ],
)
def test_system_assignment_requires_named_process_actor_and_reason(
    basic_world,
    field,
    value,
):
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    kwargs = {
        "ticket_id": ticket.id,
        "assignee_id": target.id,
        "actor_subject": "automation:rule-1",
        "actor_display_name": "Automation rule: Assign work",
        "source_process": "automation.rule",
        "reason": "Rule selected the owner.",
    }
    kwargs[field] = value

    with pytest.raises(TicketValidationError) as caught:
        assign_ticket_by_system(**kwargs)

    assert caught.value.fields == {field: ["This field is required."]}
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


def test_system_assignment_revalidates_target_and_records_system_actor(basic_world):
    ineligible = _user(["it-agents"])
    ticket = _ticket(basic_world, status="triage")

    with pytest.raises(TicketValidationError) as caught:
        assign_ticket_by_system(
            ticket_id=ticket.id,
            assignee_id=ineligible.id,
            actor_subject="automation:rule-1",
            actor_display_name="Automation rule: Assign work",
            source_process="automation.rule",
            reason="Rule selected the owner.",
        )
    assert caught.value.fields == {
        "assignee_id": ["Select an eligible assignee."],
    }

    target = _user(["ops-agents"], display_name="Automated Owner")
    result = assign_ticket_by_system(
        ticket_id=ticket.id,
        assignee_id=target.id,
        actor_subject="automation:rule-1",
        actor_display_name="Automation rule: Assign work",
        source_process="automation.rule",
        reason="Rule selected the owner.",
    )

    event = TicketCustodyEvent.objects.get(ticket=ticket)
    assert result.receipt.performed_by == AssignmentActor(
        kind="system",
        subject="automation:rule-1",
        display_name="Automation rule: Assign work",
    )
    assert event.actor_kind == "system"
    assert event.actor_subject == "automation:rule-1"
    assert event.source_process == "automation.rule"
    assert event.reason == "Rule selected the owner."
    result.ticket.refresh_from_db()
    assert result.ticket.status.code == "triage"
    assert not TransitionHistory.objects.filter(ticket=ticket).exists()


def _set_bounded_database_timeouts() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '3s'")
        cursor.execute("SET LOCAL statement_timeout = '7s'")


def _join_threads(*threads: Thread) -> None:
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads), "authority race worker hung"


@pytest.mark.django_db(transaction=True)
def test_concurrent_target_deactivation_wins_then_assignment_revalidates_and_fails(
    basic_world,
):
    if connection.vendor != "postgresql":
        pytest.skip("Authority lock ordering requires PostgreSQL row locks.")
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    mutation_locked = Event()
    release_mutation = Event()
    assignment_finished = Event()
    errors: list[BaseException] = []
    assignment_errors: list[BaseException] = []

    def deactivate_target() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                locked = lock_user_authorities((target.id,))[target.id].user
                locked.is_active = False
                locked.save(update_fields=["is_active"])
                mutation_locked.set()
                if not release_mutation.wait(timeout=5):
                    raise TimeoutError("target deactivation was not released")
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    def assign_after_deactivation_started() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                assign_ticket(
                    ticket_id=ticket.id,
                    actor=User.objects.get(pk=actor.pk),
                    assignee_id=target.id,
                    expected_updated_at=ticket.updated_at,
                )
        except BaseException as exc:
            assignment_errors.append(exc)
        finally:
            assignment_finished.set()
            close_old_connections()

    mutation_thread = Thread(target=deactivate_target, daemon=True)
    assignment_thread = Thread(target=assign_after_deactivation_started, daemon=True)
    try:
        mutation_thread.start()
        assert mutation_locked.wait(timeout=5)
        assignment_thread.start()
        assert not assignment_finished.wait(timeout=0.5)
    finally:
        release_mutation.set()
        _join_threads(mutation_thread, assignment_thread)

    if errors:
        raise errors[0]
    assert len(assignment_errors) == 1
    assert isinstance(assignment_errors[0], TicketValidationError)
    assert assignment_errors[0].fields == {
        "assignee_id": ["Select an eligible assignee."],
    }
    ticket.refresh_from_db()
    target.refresh_from_db()
    assert target.is_active is False
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


@pytest.mark.django_db(transaction=True)
def test_assignment_wins_then_concurrent_grant_revocation_waits_until_commit(
    basic_world,
    monkeypatch,
):
    if connection.vendor != "postgresql":
        pytest.skip("Authority lock ordering requires PostgreSQL row locks.")
    actor = _user(["ops-supervisors"])
    target = _user(display_name="Locked Estate Examiner")
    role = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[{"domain": "operational"}],
    )
    grant = UserRole.objects.create(user=target, role=role)
    ticket = _ticket(basic_world)
    authority_locked = Event()
    release_assignment = Event()
    revocation_finished = Event()
    errors: list[BaseException] = []
    assignment_results = []
    original = assignment_service.eligible_assignee_candidate

    def pause_after_authority_lock(locked_ticket, user, *, snapshot):
        authority_locked.set()
        if not release_assignment.wait(timeout=5):
            raise TimeoutError("assignment authority lock was not released")
        return original(locked_ticket, user, snapshot=snapshot)

    monkeypatch.setattr(
        assignment_service,
        "eligible_assignee_candidate",
        pause_after_authority_lock,
    )

    def run_assignment() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                assignment_results.append(
                    assign_ticket(
                        ticket_id=ticket.id,
                        actor=User.objects.get(pk=actor.pk),
                        assignee_id=target.id,
                        expected_updated_at=ticket.updated_at,
                    )
                )
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    def revoke_grant() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                lock_user_authorities((target.id,))
                UserRole.objects.filter(pk=grant.pk).delete()
        except BaseException as exc:
            errors.append(exc)
        finally:
            revocation_finished.set()
            close_old_connections()

    assignment_thread = Thread(target=run_assignment, daemon=True)
    revocation_thread = Thread(target=revoke_grant, daemon=True)
    try:
        assignment_thread.start()
        assert authority_locked.wait(timeout=5)
        revocation_thread.start()
        assert not revocation_finished.wait(timeout=0.5)
    finally:
        release_assignment.set()
        _join_threads(assignment_thread, revocation_thread)

    if errors:
        raise errors[0]
    assert len(assignment_results) == 1
    ticket.refresh_from_db()
    assert ticket.assignee_id == target.id
    assert not UserRole.objects.filter(pk=grant.pk).exists()
    assert _assignment_rows(ticket) == (1, 1, 1)


@pytest.mark.django_db(transaction=True)
def test_concurrent_precedence_grant_wins_then_assignment_uses_fresh_locked_facts(
    basic_world,
):
    if connection.vendor != "postgresql":
        pytest.skip("Authority lock ordering requires PostgreSQL row locks.")
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    invalid_role = Role.objects.create(
        keycloak_role="invalid-functional-role",
        name="Invalid functional role",
        scopes={"domain": "operational"},
    )
    ticket = _ticket(basic_world)
    mutation_locked = Event()
    release_mutation = Event()
    assignment_finished = Event()
    errors: list[BaseException] = []
    assignment_errors: list[BaseException] = []

    def add_precedence_grant() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                lock_user_authorities((target.id,))
                UserRole.objects.create(user_id=target.id, role_id=invalid_role.id)
                mutation_locked.set()
                if not release_mutation.wait(timeout=5):
                    raise TimeoutError("precedence mutation was not released")
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    def assign_after_precedence_change_started() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                assign_ticket(
                    ticket_id=ticket.id,
                    actor=User.objects.get(pk=actor.pk),
                    assignee_id=target.id,
                    expected_updated_at=ticket.updated_at,
                )
        except BaseException as exc:
            assignment_errors.append(exc)
        finally:
            assignment_finished.set()
            close_old_connections()

    mutation_thread = Thread(target=add_precedence_grant, daemon=True)
    assignment_thread = Thread(
        target=assign_after_precedence_change_started,
        daemon=True,
    )
    try:
        mutation_thread.start()
        assert mutation_locked.wait(timeout=5)
        assignment_thread.start()
        assert not assignment_finished.wait(timeout=0.5)
    finally:
        release_mutation.set()
        _join_threads(mutation_thread, assignment_thread)

    if errors:
        raise errors[0]
    assert len(assignment_errors) == 1
    assert isinstance(assignment_errors[0], TicketValidationError)
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


def _assert_actor_mutation_wins_and_assignment_fails(
    *,
    actor: User,
    target: User,
    ticket: Ticket,
    mutate_locked_actor: Callable[[User], None],
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Authority lock ordering requires PostgreSQL row locks.")
    mutation_locked = Event()
    release_mutation = Event()
    assignment_finished = Event()
    mutation_errors: list[BaseException] = []
    assignment_errors: list[BaseException] = []

    def mutate_actor() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                locked_actor = lock_user_authorities((actor.id,))[actor.id].user
                mutate_locked_actor(locked_actor)
                mutation_locked.set()
                if not release_mutation.wait(timeout=5):
                    raise TimeoutError("actor authority mutation was not released")
        except BaseException as exc:
            mutation_errors.append(exc)
        finally:
            close_old_connections()

    def assign_with_pre_mutation_actor() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                assign_ticket(
                    ticket_id=ticket.id,
                    actor=actor,
                    assignee_id=target.id,
                    expected_updated_at=ticket.updated_at,
                )
        except BaseException as exc:
            assignment_errors.append(exc)
        finally:
            assignment_finished.set()
            close_old_connections()

    mutation_thread = Thread(target=mutate_actor, daemon=True)
    assignment_thread = Thread(target=assign_with_pre_mutation_actor, daemon=True)
    try:
        mutation_thread.start()
        assert mutation_locked.wait(timeout=5)
        assignment_thread.start()
        assert not assignment_finished.wait(timeout=0.5)
    finally:
        release_mutation.set()
        _join_threads(mutation_thread, assignment_thread)

    if mutation_errors:
        raise mutation_errors[0]
    assert len(assignment_errors) == 1
    assert isinstance(assignment_errors[0], TicketScopeError | TicketPermissionError)
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("role_key", "domain", "target_groups"),
    [
        ("supervisor-operational", Ticket.Domain.OPERATIONAL, ["ops-agents"]),
        ("lead-it", Ticket.Domain.IT, ["it-agents"]),
    ],
)
def test_concurrent_actor_leadership_revocation_cannot_use_stale_authority(
    basic_world,
    role_key,
    domain,
    target_groups,
):
    actor = _user()
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_key,
        scopes=[{"domain": domain}],
    )
    grant = UserRole.objects.create(user=actor, role=role)
    target = _user(target_groups)
    ticket = _ticket(basic_world, domain=domain)

    _assert_actor_mutation_wins_and_assignment_fails(
        actor=actor,
        target=target,
        ticket=ticket,
        mutate_locked_actor=lambda _actor: UserRole.objects.filter(pk=grant.pk).delete(),
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_actor_precedence_addition_suppresses_stale_group_authority(
    basic_world,
):
    actor = _user(["ops-supervisors"])
    invalid_role = Role.objects.create(
        keycloak_role="invalid-actor-role",
        name="Invalid actor role",
        scopes={"domain": "operational"},
    )
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    _assert_actor_mutation_wins_and_assignment_fails(
        actor=actor,
        target=target,
        ticket=ticket,
        mutate_locked_actor=lambda locked_actor: UserRole.objects.create(
            user=locked_actor,
            role=invalid_role,
        ),
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_actor_legacy_group_removal_cannot_use_stale_authority(
    basic_world,
):
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    def remove_groups(locked_actor: User) -> None:
        locked_actor.keycloak_groups = []
        locked_actor.save(update_fields=["keycloak_groups"])

    _assert_actor_mutation_wins_and_assignment_fails(
        actor=actor,
        target=target,
        ticket=ticket,
        mutate_locked_actor=remove_groups,
    )


@pytest.mark.parametrize(
    ("mode", "actor_groups", "status"),
    [
        ("transfer", ["ops-supervisors"], "new"),
        ("self", ["ops-agents"], "new"),
        ("auto-transition", ["ops-supervisors"], "triage"),
    ],
)
def test_request_local_auditor_claim_denies_assignment_with_old_snapshot(
    basic_world,
    mode,
    actor_groups,
    status,
):
    actor = _user(actor_groups)
    snapshot = get_authority_snapshot(actor)
    actor._groups = [*actor_groups, "auditors"]
    target = actor if mode == "self" else _user(["ops-agents"])
    ticket = _ticket(basic_world, status=status)
    previous_updated_at = ticket.updated_at

    with pytest.raises(TicketPermissionError):
        assign_ticket(
            ticket_id=ticket.id,
            actor=actor,
            assignee_id=target.id,
            expected_updated_at=ticket.updated_at,
            snapshot=snapshot,
        )

    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert ticket.status.code == status
    assert ticket.updated_at == previous_updated_at
    assert _assignment_rows(ticket) == (0, 0, 0)
    assert not TransitionHistory.objects.filter(ticket=ticket).exists()


def test_non_auditor_request_groups_cannot_widen_old_assignment_snapshot(
    basic_world,
):
    actor = _user()
    snapshot = get_authority_snapshot(actor)
    actor._groups = ["ops-supervisors"]
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    with pytest.raises(TicketScopeError):
        assign_ticket(
            ticket_id=ticket.id,
            actor=actor,
            assignee_id=target.id,
            expected_updated_at=ticket.updated_at,
            snapshot=snapshot,
        )

    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    assert _assignment_rows(ticket) == (0, 0, 0)


def test_non_auditor_request_groups_do_not_break_locked_positive_authority(
    basic_world,
):
    actor = _user(["ops-agents"])
    snapshot = get_authority_snapshot(actor)
    supervisor_role = Role.objects.create(
        keycloak_role="supervisor-operational",
        name="Operational supervisor",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=actor, role=supervisor_role)
    actor._groups = ["it-agents"]
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)

    result = assign_ticket(
        ticket_id=ticket.id,
        actor=actor,
        assignee_id=target.id,
        expected_updated_at=ticket.updated_at,
        snapshot=snapshot,
    )

    assert result.ticket.assignee_id == target.id
    assert _assignment_rows(ticket) == (1, 1, 1)
