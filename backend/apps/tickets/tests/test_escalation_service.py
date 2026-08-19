from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity_access.authority_lock import lock_user_authorities
from apps.identity_access.models import Role, User, UserRole
from apps.identity_access.scope import get_authority_snapshot
from apps.organisations.models import Office
from apps.sla.models import SlaInstance, SlaPauseHistory, SlaPolicy
from apps.tickets import services
from apps.tickets.eligibility import eligible_escalation_supervisors
from apps.tickets.escalation import (
    IneligibleEscalationSupervisor,
    prepare_escalation_assignment,
)
from apps.tickets.models import OutboxEvent, Ticket
from apps.workflow.models import Status, TransitionHistory

pytestmark = pytest.mark.django_db


def _ticket(
    basic_world,
    *,
    status_code: str = "in_progress",
    assignee: User | None = None,
    domain: str = Ticket.Domain.OPERATIONAL,
) -> Ticket:
    service = (
        basic_world["gen_info"] if domain == Ticket.Domain.OPERATIONAL else basic_world["it_inc"]
    )
    prefix = "OP" if domain == Ticket.Domain.OPERATIONAL else "IT"
    return Ticket.objects.create(
        number=f"{prefix}-202607-{Ticket.objects.count() + 965001:06d}",
        domain=domain,
        title="Escalation assignment planning contract",
        status=Status.objects.get(
            domain=domain,
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
    # Operational and IT authority is confined to the officer's office, so
    # every staff actor is based at the seeded ``basic_world`` office.
    return User.objects.create(
        username=f"escalation-{suffix}",
        keycloak_subject=f"escalation-subject-{suffix}",
        display_name=display_name,
        keycloak_groups=groups or [],
        is_active=active,
        office=Office.objects.get(code="TST-1"),
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
        expires_at=(timezone.now() - timedelta(seconds=1) if expired else None),
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


def _sla_instance(ticket: Ticket) -> SlaInstance:
    policy = SlaPolicy.objects.get(
        domain=ticket.domain,
        priority=ticket.priority,
    )
    return SlaInstance.objects.create(
        ticket=ticket,
        policy=policy,
        kind="resolution",
        state=SlaInstance.State.ACTIVE,
        due_at=ticket.created_at + timedelta(hours=1),
    )


def _assert_no_transition_evidence(
    ticket: Ticket,
    *,
    status_code: str,
    assignee_id: UUID | None,
    sla: SlaInstance,
) -> None:
    ticket.refresh_from_db()
    sla.refresh_from_db()
    assert ticket.status.code == status_code
    assert ticket.assignee_id == assignee_id
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 0
    assert sla.state == SlaInstance.State.ACTIVE
    assert SlaPauseHistory.objects.filter(instance=sla).count() == 0
    assert AuditEvent.objects.filter(object_id=str(ticket.id)).count() == 0
    assert ticket.custody_events.count() == 0
    assert OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count() == 0


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
        locked_actor, locked_authorities = services._lock_and_revalidate_mutation_authorities(
            ticket=ticket,
            actor=actor,
            request=None,
            initial_snapshot=initial_snapshot,
            additional_user_ids={previous.id, supervisor.id},
        )

    expected_ids = tuple(sorted({actor.id, previous.id, supervisor.id}, key=str))
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


def test_escalation_transition_reports_reason_and_supervisor_together(
    basic_world,
) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    ticket = _ticket(basic_world, assignee=actor)
    sla = _sla_instance(ticket)

    with pytest.raises(services.TransitionError) as exc_info:
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="escalated",
        )

    assert exc_info.value.fields == {
        "reason": ["This field is required."],
        "supervisor_id": ["Select an escalation supervisor."],
    }
    _assert_no_transition_evidence(
        ticket,
        status_code="in_progress",
        assignee_id=actor.id,
        sla=sla,
    )


def test_it_escalation_preserves_owner_and_records_only_transition_evidence(
    basic_world,
    monkeypatch,
) -> None:
    actor = _user(display_name="IT Agent", groups=["it-agents"])
    owner = _user(display_name="Current IT Owner", groups=["it-agents"])
    ticket = _ticket(
        basic_world,
        domain=Ticket.Domain.IT,
        assignee=owner,
    )
    real_lock_user_authorities = lock_user_authorities
    lock_calls: list[tuple[UUID, ...]] = []

    def record_combined_lock(user_ids) -> dict:
        ordered_ids = tuple(sorted(set(user_ids), key=str))
        lock_calls.append(ordered_ids)
        return real_lock_user_authorities(ordered_ids)

    def reject_assignment_planning(*args, **kwargs):
        raise AssertionError("IT escalation must not plan a supervisor assignment")

    monkeypatch.setattr(
        services,
        "lock_user_authorities",
        record_combined_lock,
    )
    monkeypatch.setattr(
        services,
        "prepare_escalation_assignment",
        reject_assignment_planning,
    )

    updated = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="escalated",
        reason="Vendor incident needs attention",
    )

    assert lock_calls == [(actor.id,)]
    assert updated.status.code == "escalated"
    assert updated.assignee_id == owner.id
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 1
    assert list(updated.custody_events.values_list("event_type", flat=True)) == ["escalated"]
    assert list(
        AuditEvent.objects.filter(object_id=str(ticket.id)).values_list(
            "action",
            flat=True,
        )
    ) == ["ticket.transitioned"]
    assert list(
        OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).values_list(
            "event_type",
            flat=True,
        )
    ) == ["ticket.transitioned"]
    transition_audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.transitioned",
    )
    assert transition_audit.payload["metadata"] == {
        "reason": "Vendor incident needs attention",
    }


def test_non_escalation_transition_rejects_supervisor_without_side_effects(
    basic_world,
) -> None:
    actor = _scoped_actor(basic_world, role_key="master")
    ticket = _ticket(basic_world, assignee=actor)
    sla = _sla_instance(ticket)

    with pytest.raises(services.TransitionError) as exc_info:
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="resolved",
            resolution_code="INFO_PROVIDED",
            resolution_summary="Requester received the answer.",
            supervisor_id=uuid4(),
        )

    assert exc_info.value.fields == {
        "supervisor_id": ["This field is only valid when escalating."],
    }
    _assert_no_transition_evidence(
        ticket,
        status_code="in_progress",
        assignee_id=actor.id,
        sla=sla,
    )


def test_escalation_assigns_supervisor_and_records_complete_evidence(
    basic_world,
    monkeypatch,
) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    supervisor = _scoped_actor(basic_world, role_key="assistant-master")
    ticket = _ticket(basic_world, assignee=actor)
    sla = _sla_instance(ticket)
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

    updated = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="escalated",
        reason="Requires delegated approval",
        supervisor_id=supervisor.id,
    )

    sla.refresh_from_db()
    assert lock_calls == [tuple(sorted({actor.id, supervisor.id}, key=str))]
    assert updated.status.code == "escalated"
    assert updated.assignee_id == supervisor.id
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 1
    assert sla.state == SlaInstance.State.ACTIVE
    assert SlaPauseHistory.objects.filter(instance=sla).count() == 0
    assert list(updated.custody_events.values_list("event_type", flat=True)) == [
        "reassigned",
        "escalated",
    ]
    assert (
        AuditEvent.objects.filter(
            object_id=str(ticket.id),
            action__in=["ticket.assignment.changed", "ticket.transitioned"],
        ).count()
        == 2
    )
    assert (
        OutboxEvent.objects.filter(
            aggregate_id=str(ticket.id),
            event_type__in=["ticket.assignment.changed", "ticket.transitioned"],
        ).count()
        == 2
    )
    assignment_audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.assignment.changed",
    )
    assert assignment_audit.actor_subject == actor.keycloak_subject
    assert assignment_audit.payload["before"] == {"assignee": str(actor.id)}
    assert assignment_audit.payload["after"] == {"assignee": str(supervisor.id)}
    assert assignment_audit.payload["metadata"] == {
        "reason": "Requires delegated approval",
        "source_process": "ticket.escalation",
    }
    transition_audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.transitioned",
    )
    assert transition_audit.payload["metadata"] == {
        "reason": "Requires delegated approval",
        "supervisor_id": str(supervisor.id),
    }
    custody = list(updated.custody_events.order_by("sequence"))
    assert custody[0].occurred_at == custody[1].occurred_at


def test_escalation_to_existing_supervisor_records_only_transition_evidence(
    basic_world,
) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    supervisor = _scoped_actor(basic_world, role_key="deputy-master")
    ticket = _ticket(basic_world, assignee=supervisor)
    sla = _sla_instance(ticket)

    updated = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="escalated",
        reason="Supervisor already owns the matter",
        supervisor_id=supervisor.id,
    )

    sla.refresh_from_db()
    assert updated.status.code == "escalated"
    assert updated.assignee_id == supervisor.id
    assert TransitionHistory.objects.filter(ticket=ticket).count() == 1
    assert sla.state == SlaInstance.State.ACTIVE
    assert SlaPauseHistory.objects.filter(instance=sla).count() == 0
    assert list(updated.custody_events.values_list("event_type", flat=True)) == ["escalated"]
    assert AuditEvent.objects.filter(object_id=str(ticket.id)).count() == 1
    assert OutboxEvent.objects.filter(aggregate_id=str(ticket.id)).count() == 1
    transition_audit = AuditEvent.objects.get(
        object_id=str(ticket.id),
        action="ticket.transitioned",
    )
    assert transition_audit.payload["metadata"] == {
        "reason": "Supervisor already owns the matter",
        "supervisor_id": str(supervisor.id),
    }


def test_stale_escalation_transition_records_no_evidence(basic_world) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    previous = _scoped_actor(basic_world, role_key="records-officer")
    supervisor = _scoped_actor(basic_world, role_key="master")
    ticket = _ticket(basic_world, assignee=previous)
    sla = _sla_instance(ticket)

    with pytest.raises(services.TicketConflictError):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at - timedelta(microseconds=1),
            to_status_code="escalated",
            reason="Stale escalation",
            supervisor_id=supervisor.id,
        )

    _assert_no_transition_evidence(
        ticket,
        status_code="in_progress",
        assignee_id=previous.id,
        sla=sla,
    )


def test_escalation_transition_revalidates_revoked_supervisor_eligibility(
    basic_world,
) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    previous = _scoped_actor(basic_world, role_key="records-officer")
    supervisor = _scoped_actor(basic_world, role_key="master")
    ticket = _ticket(basic_world, assignee=previous)
    sla = _sla_instance(ticket)
    assert [candidate.id for candidate in eligible_escalation_supervisors(ticket)] == [
        supervisor.id
    ]
    UserRole.objects.filter(user=supervisor).delete()

    with pytest.raises(services.TransitionError) as exc_info:
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="escalated",
            reason="Candidate was visible before revocation",
            supervisor_id=supervisor.id,
        )

    assert exc_info.value.fields == {
        "supervisor_id": ["Select an eligible escalation supervisor."],
    }
    _assert_no_transition_evidence(
        ticket,
        status_code="in_progress",
        assignee_id=previous.id,
        sla=sla,
    )


def test_escalation_transition_rolls_back_ticket_sla_history_and_evidence(
    basic_world,
    monkeypatch,
) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    previous = _scoped_actor(basic_world, role_key="records-officer")
    supervisor = _scoped_actor(basic_world, role_key="master")
    ticket = _ticket(basic_world, assignee=previous)
    sla = _sla_instance(ticket)
    real_record_ticket_event = services.record_ticket_event

    def mutate_sla(**kwargs) -> None:
        SlaInstance.objects.filter(ticket=kwargs["ticket"]).update(
            state=SlaInstance.State.CANCELLED
        )

    def fail_after_assignment_evidence(**kwargs):
        result = real_record_ticket_event(**kwargs)
        if kwargs["action"] == "ticket.assignment.changed":
            raise RuntimeError("downstream transition evidence failed")
        return result

    monkeypatch.setattr(
        "apps.sla.services.sync_slas_for_transition",
        mutate_sla,
    )
    monkeypatch.setattr(
        services,
        "record_ticket_event",
        fail_after_assignment_evidence,
    )

    with pytest.raises(
        RuntimeError,
        match="downstream transition evidence failed",
    ):
        services.transition_ticket(
            ticket_id=ticket.id,
            actor=actor,
            expected_updated_at=ticket.updated_at,
            to_status_code="escalated",
            reason="Must commit as one unit",
            supervisor_id=supervisor.id,
        )

    _assert_no_transition_evidence(
        ticket,
        status_code="in_progress",
        assignee_id=previous.id,
        sla=sla,
    )


def test_non_escalation_transition_custody_preserves_history_timestamp(
    basic_world,
) -> None:
    actor = _scoped_actor(basic_world, role_key="examiner")
    ticket = _ticket(basic_world, status_code="new", assignee=actor)

    updated = services.transition_ticket(
        ticket_id=ticket.id,
        actor=actor,
        expected_updated_at=ticket.updated_at,
        to_status_code="triage",
    )

    history = TransitionHistory.objects.get(ticket=ticket)
    custody = updated.custody_events.get()
    assert custody.occurred_at == history.occurred_at
