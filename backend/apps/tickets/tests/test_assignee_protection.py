from __future__ import annotations

from threading import Event, Thread
from uuid import uuid4

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import PROTECT, SET_NULL, ProtectedError

from apps.audit.models import AuditEvent
from apps.identity_access.models import User
from apps.tickets import assignment as assignment_service
from apps.tickets.assignment import assign_ticket
from apps.tickets.models import OutboxEvent, Ticket, TicketCustodyEvent
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db(transaction=True)


def _user(groups: list[str]) -> User:
    user = User.objects.create(
        username=f"assignee-protection-{uuid4().hex}",
        keycloak_subject=f"assignee-protection-subject-{uuid4().hex}",
        keycloak_groups=groups,
    )
    user._groups = list(groups)
    return user


def _ticket(basic_world) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-PROTECT-{uuid4().hex[:12]}",
        domain=Ticket.Domain.OPERATIONAL,
        title="Protected assignee history",
        status=Status.objects.get(domain=Ticket.Domain.OPERATIONAL, code="new"),
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
    )


def _assign(ticket: Ticket, actor: User, target: User) -> None:
    assign_ticket(
        ticket_id=ticket.id,
        actor=actor,
        assignee_id=target.id,
        expected_updated_at=ticket.updated_at,
    )


def _event_counts(ticket: Ticket) -> tuple[int, int, int]:
    return (
        AuditEvent.objects.filter(
            object_id=str(ticket.id),
            action="ticket.assignment.changed",
        ).count(),
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id),
            event_type="ticket.assignment.changed",
        ).count(),
        TicketCustodyEvent.objects.filter(ticket=ticket, event_type="assigned").count(),
    )


def _set_bounded_database_timeouts() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '3s'")
        cursor.execute("SET LOCAL statement_timeout = '7s'")


def _join_threads(*threads: Thread) -> None:
    for thread in threads:
        if thread.ident is not None:
            thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads), "assignee deletion race hung"


def test_assigned_user_hard_delete_is_protected_without_changing_custody(
    basic_world,
) -> None:
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    _assign(ticket, actor, target)
    before_counts = _event_counts(ticket)

    with pytest.raises(ProtectedError):
        target.delete()

    ticket.refresh_from_db()
    assert User.objects.filter(pk=target.pk).exists()
    assert ticket.assignee_id == target.id
    assert _event_counts(ticket) == before_counts == (1, 1, 1)


def test_assignment_wins_concurrent_user_delete_without_deadlock_or_silent_unassignment(
    basic_world,
    monkeypatch,
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Assignee protection concurrency requires PostgreSQL row locks.")
    actor = _user(["ops-supervisors"])
    target = _user(["ops-agents"])
    ticket = _ticket(basic_world)
    target_locked = Event()
    release_assignment = Event()
    delete_finished = Event()
    assignment_results = []
    assignment_errors: list[BaseException] = []
    delete_errors: list[BaseException] = []
    original_candidate = assignment_service.eligible_assignee_candidate

    def pause_with_target_locked(locked_ticket, user, *, snapshot):
        if user.pk == target.pk:
            target_locked.set()
            if not release_assignment.wait(timeout=5):
                raise TimeoutError("assignment target lock was not released")
        return original_candidate(locked_ticket, user, snapshot=snapshot)

    monkeypatch.setattr(
        assignment_service,
        "eligible_assignee_candidate",
        pause_with_target_locked,
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
            assignment_errors.append(exc)
        finally:
            close_old_connections()

    def delete_target() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                User.objects.get(pk=target.pk).delete()
        except BaseException as exc:
            delete_errors.append(exc)
        finally:
            delete_finished.set()
            close_old_connections()

    assignment_thread = Thread(target=run_assignment, daemon=True)
    delete_thread = Thread(target=delete_target, daemon=True)
    try:
        assignment_thread.start()
        assert target_locked.wait(timeout=5)
        delete_thread.start()
        assert not delete_finished.wait(timeout=0.5)
    finally:
        release_assignment.set()
        _join_threads(assignment_thread, delete_thread)

    if assignment_errors:
        raise assignment_errors[0]
    assert len(assignment_results) == 1
    assert len(delete_errors) == 1
    assert isinstance(delete_errors[0], IntegrityError)
    ticket.refresh_from_db()
    assert User.objects.filter(pk=target.pk).exists()
    assert ticket.assignee_id == target.id
    assert _event_counts(ticket) == (1, 1, 1)


def test_0009_changes_assignee_deletion_from_set_null_to_protect_and_rolls_back() -> None:
    from django.db.migrations.executor import MigrationExecutor

    previous = "0008_harden_ticket_custody_contract"
    leaf = "0009_protect_ticket_assignee"
    current_leaf = "0010_protect_ticket_queue"
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", previous)])
        before_apps = executor.loader.project_state(
            [("tickets", previous)]
        ).apps
        before_field = before_apps.get_model("tickets", "Ticket")._meta.get_field("assignee")
        assert before_field.remote_field.on_delete is SET_NULL

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", leaf)])
        after_apps = executor.loader.project_state([("tickets", leaf)]).apps
        after_field = after_apps.get_model("tickets", "Ticket")._meta.get_field("assignee")
        assert after_field.remote_field.on_delete is PROTECT

        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", previous)])
        rollback_apps = executor.loader.project_state([("tickets", previous)]).apps
        rollback_field = rollback_apps.get_model("tickets", "Ticket")._meta.get_field(
            "assignee"
        )
        assert rollback_field.remote_field.on_delete is SET_NULL
    finally:
        MigrationExecutor(connection).migrate([("tickets", current_leaf)])
