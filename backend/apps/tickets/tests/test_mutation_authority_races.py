from __future__ import annotations

from datetime import datetime
from threading import Event, Thread
from typing import Literal
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection, transaction

from apps.audit.models import AuditEvent
from apps.identity_access.authority_lock import lock_user_authorities
from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import AuthoritySnapshot, get_authority_snapshot
from apps.organisations.models import ServiceLocation
from apps.tickets import services
from apps.tickets.models import (
    OutboxEvent,
    Ticket,
    TicketCustodyEvent,
    TicketMessage,
    TicketNote,
)
from apps.workflow.models import Status, TransitionHistory

pytestmark = pytest.mark.django_db(transaction=True)

MutationKind = Literal["work_state", "transition", "message", "note"]
AuthorityChange = Literal[
    "designation_revoked",
    "designation_narrowed",
    "auditor_role_added",
    "auditor_group_added",
]
CachedAuditorSource = Literal["persisted_role", "django_group"]

MUTATION_KINDS: tuple[MutationKind, ...] = (
    "work_state",
    "transition",
    "message",
    "note",
)
AUTHORITY_CHANGES: tuple[AuthorityChange, ...] = (
    "designation_revoked",
    "designation_narrowed",
    "auditor_role_added",
    "auditor_group_added",
)
CACHED_AUDITOR_SOURCES: tuple[CachedAuditorSource, ...] = (
    "persisted_role",
    "django_group",
)


def _user() -> User:
    suffix = uuid4().hex
    return User.objects.create(
        username=f"authority-race-{suffix}",
        keycloak_subject=f"authority-race-subject-{suffix}",
        display_name="Authority Race Actor",
        keycloak_groups=[],
        is_active=True,
    )


def _ticket(basic_world) -> Ticket:
    queue = ServiceLocation.objects.create(
        office=basic_world["office"],
        name=f"Authority race queue {uuid4().hex}",
    )
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 980001:06d}",
        domain=Ticket.Domain.OPERATIONAL,
        title="Ordinary authority race",
        status=Status.objects.get(domain=Ticket.Domain.OPERATIONAL, code="new"),
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        queue=queue,
    )


def _designation_actor(ticket: Ticket) -> tuple[User, Role, UserRole]:
    actor = _user()
    role = Role.objects.create(
        keycloak_role="estate-examiner",
        name="Estate Examiner",
        scopes=[
            {
                "domain": Ticket.Domain.OPERATIONAL,
                "office": str(ticket.office_id),
                "service": str(ticket.service_id),
                "queue": str(ticket.queue_id),
            }
        ],
    )
    grant = UserRole.objects.create(
        user=actor,
        role=role,
        office=ticket.office,
    )
    return actor, role, grant


def _set_bounded_database_timeouts() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '3s'")
        cursor.execute("SET LOCAL statement_timeout = '7s'")


def _join_threads(*threads: Thread) -> None:
    for thread in threads:
        if thread.ident is not None:
            thread.join(timeout=12)
    assert all(not thread.is_alive() for thread in threads), "authority race worker hung"


def _invoke_mutation(
    kind: MutationKind,
    *,
    ticket: Ticket,
    actor: User,
    snapshot: AuthoritySnapshot,
) -> object:
    if kind == "work_state":
        return services.update_work_state(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            changes={"team": "Race-updated team"},
            snapshot=snapshot,
        )
    if kind == "transition":
        return services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="triage",
            snapshot=snapshot,
        )
    if kind == "message":
        return services.add_message(
            ticket=ticket,
            direction=TicketMessage.Direction.OUTBOUND,
            body_text="Race-protected public reply",
            actor_subject=actor.keycloak_subject,
            author_subject=actor.keycloak_subject,
            author_label=actor.display_name,
            delivery_status="failed",
            actor=actor,
            snapshot=snapshot,
        )
    return services.add_internal_note(
        ticket=ticket,
        body="Race-protected internal note",
        author_subject=actor.keycloak_subject,
        actor=actor,
        snapshot=snapshot,
    )


def _apply_authority_change(
    change: AuthorityChange,
    *,
    actor: User,
    role: Role,
    grant: UserRole,
    ticket: Ticket,
) -> None:
    if change == "designation_revoked":
        UserRole.objects.filter(pk=grant.pk).delete()
        return
    if change == "designation_narrowed":
        locked_role = Role.objects.get(pk=role.pk)
        locked_role.scopes = [
            {
                "domain": Ticket.Domain.OPERATIONAL,
                "office": str(ticket.office_id),
                "service": str(uuid4()),
                "queue": str(ticket.queue_id),
            }
        ]
        locked_role.save(update_fields=["scopes"])
        return
    if change == "auditor_role_added":
        auditor_role = Role.objects.create(
            keycloak_role="auditor",
            name="Auditor",
            scopes=[{"domain": Ticket.Domain.OPERATIONAL}],
        )
        UserRole.objects.create(user_id=actor.id, role_id=auditor_role.id)
        return
    auditor_group = Group.objects.create(name="auditors")
    User.groups.through.objects.create(user_id=actor.id, group_id=auditor_group.id)


def _assert_no_mutation_side_effects(
    ticket: Ticket,
    *,
    previous_updated_at: datetime,
) -> None:
    ticket.refresh_from_db()
    assert ticket.team == ""
    assert ticket.status.code == "new"
    assert ticket.first_responded_at is None
    assert ticket.updated_at == previous_updated_at
    assert not TicketMessage.objects.filter(ticket=ticket).exists()
    assert not TicketNote.objects.filter(ticket=ticket).exists()
    assert not AuditEvent.objects.filter(object_id=str(ticket.id)).exists()
    assert not OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).exists()
    assert not TicketCustodyEvent.objects.filter(ticket=ticket).exists()
    assert not TransitionHistory.objects.filter(ticket=ticket).exists()


def _assert_successful_mutation(kind: MutationKind, ticket: Ticket) -> None:
    ticket.refresh_from_db()
    expected_actions = {
        "work_state": "ticket.work_state.changed",
        "transition": "ticket.transitioned",
        "message": "ticket.message.created",
        "note": "ticket.note.created",
    }
    if kind == "work_state":
        assert ticket.team == "Race-updated team"
    elif kind == "transition":
        assert ticket.status.code == "triage"
        assert TransitionHistory.objects.filter(ticket=ticket).count() == 1
        assert TicketCustodyEvent.objects.filter(ticket=ticket).count() == 1
    elif kind == "message":
        assert TicketMessage.objects.filter(ticket=ticket).count() == 1
    else:
        assert TicketNote.objects.filter(ticket=ticket).count() == 1
    action = expected_actions[kind]
    assert AuditEvent.objects.filter(object_id=str(ticket.id), action=action).count() == 1
    assert OutboxEvent.objects.filter(
        aggregate_id=str(ticket.id),
        event_type=action,
    ).count() == 1


@pytest.mark.parametrize("kind", MUTATION_KINDS)
@pytest.mark.parametrize("authority_change", AUTHORITY_CHANGES)
def test_committed_authority_change_blocks_stale_ordinary_mutation(
    basic_world,
    monkeypatch,
    kind: MutationKind,
    authority_change: AuthorityChange,
) -> None:
    """A committed authority loss must win over a stale request snapshot."""
    if connection.vendor != "postgresql":
        pytest.skip("Authority lock ordering requires PostgreSQL row locks.")
    ticket = _ticket(basic_world)
    actor, role, grant = _designation_actor(ticket)
    stale_snapshot = get_authority_snapshot(actor)
    previous_updated_at = ticket.updated_at
    authority_changed = Event()
    release_authority_change = Event()
    actor_lock_attempted = Event()
    mutation_finished = Event()
    authority_errors: list[BaseException] = []
    mutation_errors: list[BaseException] = []
    real_lock_user_authorities = lock_user_authorities

    def announce_actor_lock(user_ids):
        actor_lock_attempted.set()
        return real_lock_user_authorities(user_ids)

    monkeypatch.setattr(
        services,
        "lock_user_authorities",
        announce_actor_lock,
    )

    def change_authority() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                lock_user_authorities((actor.id,))
                _apply_authority_change(
                    authority_change,
                    actor=actor,
                    role=role,
                    grant=grant,
                    ticket=ticket,
                )
                authority_changed.set()
                if not release_authority_change.wait(timeout=5):
                    raise TimeoutError("authority change was not released")
        except BaseException as exc:
            authority_errors.append(exc)
        finally:
            close_old_connections()

    def mutate_with_stale_snapshot() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                _invoke_mutation(
                    kind,
                    ticket=ticket,
                    actor=actor,
                    snapshot=stale_snapshot,
                )
        except BaseException as exc:
            mutation_errors.append(exc)
        finally:
            mutation_finished.set()
            close_old_connections()

    authority_thread = Thread(target=change_authority, daemon=True)
    mutation_thread = Thread(target=mutate_with_stale_snapshot, daemon=True)
    try:
        authority_thread.start()
        assert authority_changed.wait(timeout=5)
        mutation_thread.start()
        assert actor_lock_attempted.wait(timeout=5)
        assert not mutation_finished.wait(timeout=0.5)
    finally:
        release_authority_change.set()
        _join_threads(authority_thread, mutation_thread)

    if authority_errors:
        raise authority_errors[0]
    assert len(mutation_errors) == 1
    assert isinstance(
        mutation_errors[0],
        services.TicketPermissionError | services.TicketScopeError,
    )
    _assert_no_mutation_side_effects(
        ticket,
        previous_updated_at=previous_updated_at,
    )


@pytest.mark.parametrize("kind", MUTATION_KINDS)
def test_ordinary_mutation_holds_actor_authority_until_commit(
    basic_world,
    monkeypatch,
    kind: MutationKind,
) -> None:
    """A mutation that owns the authority lock completes before revocation."""
    if connection.vendor != "postgresql":
        pytest.skip("Authority lock ordering requires PostgreSQL row locks.")
    ticket = _ticket(basic_world)
    actor, _role, grant = _designation_actor(ticket)
    snapshot = get_authority_snapshot(actor)
    authority_locked = Event()
    release_mutation = Event()
    revocation_finished = Event()
    mutation_errors: list[BaseException] = []
    revocation_errors: list[BaseException] = []
    mutation_results: list[object] = []
    real_lock_user_authorities = lock_user_authorities

    def pause_after_authority_lock(user_ids):
        locked = real_lock_user_authorities(user_ids)
        authority_locked.set()
        if not release_mutation.wait(timeout=5):
            raise TimeoutError("ordinary mutation authority lock was not released")
        return locked

    monkeypatch.setattr(
        services,
        "lock_user_authorities",
        pause_after_authority_lock,
        raising=False,
    )

    def run_mutation() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                mutation_results.append(
                    _invoke_mutation(
                        kind,
                        ticket=ticket,
                        actor=actor,
                        snapshot=snapshot,
                    )
                )
        except BaseException as exc:
            mutation_errors.append(exc)
        finally:
            close_old_connections()

    def revoke_designation() -> None:
        close_old_connections()
        try:
            with transaction.atomic():
                _set_bounded_database_timeouts()
                real_lock_user_authorities((actor.id,))
                UserRole.objects.filter(pk=grant.pk).delete()
        except BaseException as exc:
            revocation_errors.append(exc)
        finally:
            revocation_finished.set()
            close_old_connections()

    mutation_thread = Thread(target=run_mutation, daemon=True)
    revocation_thread = Thread(target=revoke_designation, daemon=True)
    try:
        mutation_thread.start()
        assert authority_locked.wait(timeout=5)
        revocation_thread.start()
        assert not revocation_finished.wait(timeout=0.5)
    finally:
        release_mutation.set()
        _join_threads(mutation_thread, revocation_thread)

    if mutation_errors:
        raise mutation_errors[0]
    if revocation_errors:
        raise revocation_errors[0]
    assert len(mutation_results) == 1
    assert not UserRole.objects.filter(pk=grant.pk).exists()
    _assert_successful_mutation(kind, ticket)


@pytest.mark.parametrize("kind", MUTATION_KINDS)
def test_request_local_auditor_claim_is_a_monotonic_ordinary_mutation_deny(
    basic_world,
    kind: MutationKind,
) -> None:
    ticket = _ticket(basic_world)
    actor, _role, _grant = _designation_actor(ticket)
    snapshot = get_authority_snapshot(actor)
    previous_updated_at = ticket.updated_at
    actor._groups = ["auditors"]

    with pytest.raises((services.TicketPermissionError, services.TicketScopeError)):
        _invoke_mutation(
            kind,
            ticket=ticket,
            actor=actor,
            snapshot=snapshot,
        )

    _assert_no_mutation_side_effects(
        ticket,
        previous_updated_at=previous_updated_at,
    )


@pytest.mark.parametrize("kind", MUTATION_KINDS)
def test_request_local_positive_groups_cannot_authorize_ordinary_mutation(
    basic_world,
    kind: MutationKind,
) -> None:
    ticket = _ticket(basic_world)
    actor = _user()
    snapshot = get_authority_snapshot(actor)
    previous_updated_at = ticket.updated_at
    actor._groups = ["ops-agents"]

    with pytest.raises((services.TicketPermissionError, services.TicketScopeError)):
        _invoke_mutation(
            kind,
            ticket=ticket,
            actor=actor,
            snapshot=snapshot,
        )

    _assert_no_mutation_side_effects(
        ticket,
        previous_updated_at=previous_updated_at,
    )


@pytest.mark.parametrize("kind", MUTATION_KINDS)
@pytest.mark.parametrize("auditor_source", CACHED_AUDITOR_SOURCES)
def test_cached_auditor_snapshot_remains_a_deny_after_source_is_removed(
    basic_world,
    kind: MutationKind,
    auditor_source: CachedAuditorSource,
) -> None:
    ticket = _ticket(basic_world)
    previous_updated_at = ticket.updated_at

    if auditor_source == "persisted_role":
        actor, _role, _grant = _designation_actor(ticket)
        auditor_role = Role.objects.create(
            keycloak_role="auditor",
            name="Auditor",
            scopes=[{"domain": Ticket.Domain.OPERATIONAL}],
        )
        auditor_fact: UserRole | Group = UserRole.objects.create(
            user=actor,
            role=auditor_role,
        )
    else:
        actor = _user()
        actor.keycloak_groups = ["ops-agents"]
        actor.save(update_fields=["keycloak_groups"])
        auditor_fact = Group.objects.create(name="auditors")
        actor.groups.add(auditor_fact)

    snapshot = get_authority_snapshot(actor)
    assert snapshot.auditor_identity or "auditor" in snapshot.capabilities

    if isinstance(auditor_fact, UserRole):
        auditor_fact.delete()
    else:
        actor.groups.remove(auditor_fact)

    with pytest.raises((services.TicketPermissionError, services.TicketScopeError)):
        _invoke_mutation(
            kind,
            ticket=ticket,
            actor=actor,
            snapshot=snapshot,
        )

    _assert_no_mutation_side_effects(
        ticket,
        previous_updated_at=previous_updated_at,
    )
