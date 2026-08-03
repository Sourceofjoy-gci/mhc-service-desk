from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from apps.identity_access.authority_lock import lock_user_authorities
from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import get_authority_snapshot
from apps.organisations.models import Office
from apps.tickets import services
from apps.tickets.escalation import (
    IneligibleEscalationSupervisor,
    prepare_escalation_assignment,
)
from apps.tickets.models import Ticket
from apps.workflow.models import Status

pytestmark = pytest.mark.django_db


def _ticket(
    basic_world,
    *,
    status_code: str = "in_progress",
    assignee: User | None = None,
) -> Ticket:
    service = basic_world["gen_info"]
    return Ticket.objects.create(
        number=f"OP-202607-{Ticket.objects.count() + 965001:06d}",
        domain=Ticket.Domain.OPERATIONAL,
        title="Escalation assignment planning contract",
        status=Status.objects.get(
            domain=Ticket.Domain.OPERATIONAL,
            code=status_code,
        ),
        channel=Ticket.Channel.INTERNAL,
        requester=basic_world["contact"],
        service=service,
        request_type=service.request_types.get(),
        office=basic_world["office"],
        assignee=assignee,
    )


def _user(
    *,
    display_name: str,
    groups: list[str] | None = None,
    active: bool = True,
) -> User:
    suffix = uuid4().hex
    return User.objects.create(
        username=f"escalation-{suffix}",
        keycloak_subject=f"escalation-subject-{suffix}",
        display_name=display_name,
        keycloak_groups=groups or [],
        is_active=active,
    )


def _grant(
    user: User,
    basic_world,
    *,
    role_key: str,
    office: Office | None = None,
    expired: bool = False,
) -> UserRole:
    resolved_office = office or basic_world["office"]
    role = Role.objects.create(
        keycloak_role=role_key,
        name=role_key.replace("-", " ").title(),
        scopes=[
            {
                "domain": Ticket.Domain.OPERATIONAL,
                "office": str(resolved_office.id),
                "service": str(basic_world["gen_info"].id),
            }
        ],
    )
    return UserRole.objects.create(
        user=user,
        role=role,
        office=resolved_office,
        expires_at=(
            timezone.now() - timedelta(seconds=1)
            if expired
            else None
        ),
    )


def _scoped_actor(
    basic_world,
    *,
    role_key: str,
    display_name: str | None = None,
    office: Office | None = None,
    expired: bool = False,
    active: bool = True,
    groups: list[str] | None = None,
) -> User:
    actor = _user(
        display_name=display_name or role_key.replace("-", " ").title(),
        groups=groups,
        active=active,
    )
    _grant(
        actor,
        basic_world,
        role_key=role_key,
        office=office,
        expired=expired,
    )
    return actor


def _assert_rejected(ticket: Ticket, target: User) -> None:
    authority_ids = {target.id}
    if ticket.assignee_id is not None:
        authority_ids.add(ticket.assignee_id)
    with transaction.atomic():
        authorities = lock_user_authorities(authority_ids)
        with pytest.raises(IneligibleEscalationSupervisor):
            prepare_escalation_assignment(
                ticket,
                target.id,
                locked_authorities=authorities,
            )


def test_prepare_escalation_assignment_builds_an_immutable_owner_plan(
    basic_world,
) -> None:
    previous = _scoped_actor(
        basic_world,
        role_key="examiner",
        display_name="Former Examiner",
        expired=True,
    )
    supervisor = _scoped_actor(
        basic_world,
        role_key="assistant-master",
        display_name="Amina Supervisor",
    )
    ticket = _ticket(basic_world, assignee=previous)

    with transaction.atomic():
        authorities = lock_user_authorities((previous.id, supervisor.id))
        plan = prepare_escalation_assignment(
            ticket,
            supervisor.id,
            locked_authorities=authorities,
        )

    assert plan.supervisor.id == supervisor.id
    assert plan.candidate.id == supervisor.id
    assert plan.candidate.designations == ("Assistant Master",)
    assert plan.changed is True
    assert plan.previous_owner is not None
    assert plan.previous_owner.id == str(previous.id)
    assert plan.previous_owner.subject == previous.keycloak_subject
    assert plan.previous_owner.display_name == "Former Examiner"
    assert plan.previous_owner.designations == ()
    assert plan.previous_owner.team_labels == ()
    assert plan.new_owner.id == str(supervisor.id)
    assert plan.new_owner.subject == supervisor.keycloak_subject
    assert plan.new_owner.display_name == "Amina Supervisor"
    assert plan.new_owner.designations == ("Assistant Master",)
    assert plan.new_owner.team_labels == ("Office Leadership",)
    with pytest.raises(FrozenInstanceError):
        plan.changed = False  # type: ignore[misc]


def test_prepare_escalation_assignment_marks_existing_supervisor_unchanged(
    basic_world,
) -> None:
    supervisor = _scoped_actor(basic_world, role_key="deputy-master")
    ticket = _ticket(basic_world, assignee=supervisor)

    with transaction.atomic():
        authorities = lock_user_authorities((supervisor.id,))
        plan = prepare_escalation_assignment(
            ticket,
            supervisor.id,
            locked_authorities=authorities,
        )

    assert plan.changed is False
    assert plan.previous_owner == plan.new_owner


def test_prepare_escalation_assignment_rejects_ordinary_assignee(
    basic_world,
) -> None:
    ticket = _ticket(basic_world)
    ordinary = _scoped_actor(basic_world, role_key="examiner")

    _assert_rejected(ticket, ordinary)


def test_prepare_escalation_assignment_rejects_legacy_supervisor(
    basic_world,
) -> None:
    ticket = _ticket(basic_world)
    legacy = _scoped_actor(basic_world, role_key="ops-supervisors")

    _assert_rejected(ticket, legacy)


def test_prepare_escalation_assignment_rejects_inactive_supervisor(
    basic_world,
) -> None:
    ticket = _ticket(basic_world)
    inactive = _scoped_actor(
        basic_world,
        role_key="assistant-master",
        active=False,
    )

    _assert_rejected(ticket, inactive)


def test_prepare_escalation_assignment_rejects_expired_supervisor(
    basic_world,
) -> None:
    ticket = _ticket(basic_world)
    expired = _scoped_actor(
        basic_world,
        role_key="assistant-master",
        expired=True,
    )

    _assert_rejected(ticket, expired)


def test_prepare_escalation_assignment_rejects_cross_office_supervisor(
    basic_world,
) -> None:
    ticket = _ticket(basic_world)
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="ESC-OTHER",
        name="Other escalation office",
    )
    cross_office = _scoped_actor(
        basic_world,
        role_key="master",
        office=other_office,
    )

    _assert_rejected(ticket, cross_office)


def test_prepare_escalation_assignment_rejects_auditor_supervisor(
    basic_world,
) -> None:
    ticket = _ticket(basic_world)
    auditor = _scoped_actor(basic_world, role_key="master")
    _grant(auditor, basic_world, role_key="auditor")

    _assert_rejected(ticket, auditor)


def test_prepare_escalation_assignment_requires_selected_authority_lock(
    basic_world,
) -> None:
    ticket = _ticket(basic_world)
    supervisor = _scoped_actor(basic_world, role_key="master")

    with pytest.raises(IneligibleEscalationSupervisor):
        prepare_escalation_assignment(
            ticket,
            supervisor.id,
            locked_authorities={},
        )


def test_prepare_escalation_assignment_requires_current_owner_authority_lock(
    basic_world,
) -> None:
    previous = _scoped_actor(basic_world, role_key="examiner")
    supervisor = _scoped_actor(basic_world, role_key="master")
    ticket = _ticket(basic_world, assignee=previous)

    with transaction.atomic():
        authorities = lock_user_authorities((supervisor.id,))
        with pytest.raises(
            RuntimeError,
            match="Current assignee authority was not locked\\.",
        ):
            prepare_escalation_assignment(
                ticket,
                supervisor.id,
                locked_authorities=authorities,
            )


def test_combined_mutation_authority_lock_is_single_and_deterministic(
    basic_world,
    monkeypatch,
) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    previous = _scoped_actor(basic_world, role_key="records-officer")
    supervisor = _scoped_actor(basic_world, role_key="master")
    ticket = _ticket(basic_world, assignee=previous)
    initial_snapshot = get_authority_snapshot(actor)
    real_lock_user_authorities = lock_user_authorities
    lock_calls: list[tuple[UUID, ...]] = []

    def record_combined_lock(user_ids) -> dict:
        ordered_ids = tuple(sorted(set(user_ids), key=str))
        lock_calls.append(ordered_ids)
        return real_lock_user_authorities(ordered_ids)

    monkeypatch.setattr(
        services,
        "lock_user_authorities",
        record_combined_lock,
    )

    with transaction.atomic():
        locked_actor, locked_authorities = (
            services._lock_and_revalidate_mutation_authorities(
                ticket=ticket,
                actor=actor,
                request=None,
                initial_snapshot=initial_snapshot,
                additional_user_ids={previous.id, supervisor.id},
            )
        )

    expected_ids = tuple(
        sorted({actor.id, previous.id, supervisor.id}, key=str)
    )
    assert lock_calls == [expected_ids]
    assert locked_actor.actor.id == actor.id
    assert set(locked_authorities) == set(expected_ids)


def test_combined_mutation_authority_lock_preserves_stale_auditor_denial(
    basic_world,
) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    auditor_grant = _grant(actor, basic_world, role_key="auditor")
    supervisor = _scoped_actor(basic_world, role_key="master")
    ticket = _ticket(basic_world)
    initial_snapshot = get_authority_snapshot(actor)
    auditor_grant.delete()

    with transaction.atomic(), pytest.raises(services.TicketPermissionError):
        services._lock_and_revalidate_mutation_authorities(
            ticket=ticket,
            actor=actor,
            request=None,
            initial_snapshot=initial_snapshot,
            additional_user_ids={supervisor.id},
        )
