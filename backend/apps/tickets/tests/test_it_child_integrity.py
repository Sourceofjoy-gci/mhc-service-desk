"""Transaction-integrity regressions for the IT child workflow."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.audit.models import AuditEvent
from apps.contacts.models import Contact
from apps.identity_access.models import Role, User, UserRole
from apps.organisations.models import Office
from apps.tickets import it_child, services
from apps.tickets.models import OutboxEvent, Ticket, TicketLink
from apps.workflow.models import Status, TransitionHistory

pytestmark = pytest.mark.django_db


def _parent(basic_world) -> Ticket:
    return services.create_ticket(
        domain="operational",
        title="Parent integrity",
        description="private parent detail",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=basic_world["gen_info"].request_types.get(code="HOURS"),
        office=basic_world["office"],
        channel="email",
        actor_subject="creator",
    )


def _create_child(parent: Ticket, basic_world) -> Ticket:
    actor = User.objects.create(
        username="ops-integrity-agent",
        keycloak_subject="ops-agent",
        keycloak_groups=["ops-agents"],
    )
    actor._groups = ["ops-agents"]
    return it_child.create_it_child_ticket(
        parent=parent,
        summary="Sanitised investigation",
        technical_priority="P3",
        actor=actor,
    )


def _it_actor() -> User:
    actor = User.objects.create(
        username="it-integrity-agent",
        keycloak_subject="it-integrity-subject",
        keycloak_groups=["it-agents"],
    )
    actor._groups = ["it-agents"]
    return actor


def _office_actor(office: Office, *, subject: str) -> User:
    actor = User.objects.create(
        username=subject,
        keycloak_subject=subject,
        keycloak_groups=[],
    )
    actor._groups = []
    role = Role.objects.create(
        keycloak_role="agent-operational",
        name=f"Office agent {subject}",
        scopes=[{"domain": "operational"}],
    )
    UserRole.objects.create(user=actor, role=role, office=office)
    return actor


def test_child_creation_revalidates_locked_parent_and_rejects_terminal_state(
    basic_world,
) -> None:
    stale_parent = _parent(basic_world)
    Ticket.objects.filter(id=stale_parent.id).update(
        status=Status.objects.get(domain="operational", code="closed")
    )
    before_ticket_ids = set(Ticket.objects.values_list("id", flat=True))

    with pytest.raises(ValueError, match="terminal parent"):
        _create_child(stale_parent, basic_world)

    assert set(Ticket.objects.values_list("id", flat=True)) == before_ticket_ids
    assert not TicketLink.objects.filter(to_ticket=stale_parent, kind="it_child").exists()


def test_child_creation_uses_fresh_parent_state_after_lock(basic_world) -> None:
    stale_parent = _parent(basic_world)
    Ticket.objects.filter(id=stale_parent.id).update(
        waiting_reason="Awaiting current privileged approval"
    )

    _create_child(stale_parent, basic_world)

    event = AuditEvent.objects.filter(
        object_id=str(stale_parent.id),
        action="ticket.transitioned",
    ).latest("occurred_at")
    assert event.payload["before"] == {
        "status": "new",
        "waiting_reason": "Awaiting current privileged approval",
    }
    stale_parent.refresh_from_db()
    assert stale_parent.status.code == "waiting_it"
    assert stale_parent.waiting_reason == "Waiting for IT"


def test_child_creation_denies_parent_moved_out_of_scope_after_pre_read(
    basic_world,
) -> None:
    stale_parent = _parent(basic_world)
    actor = _office_actor(basic_world["office"], subject="old-office-agent")
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="IT-CHILD-OTHER",
        name="Other child office",
    )
    Ticket.objects.filter(id=stale_parent.id).update(office=other_office)
    before_ids = set(Ticket.objects.values_list("id", flat=True))

    with pytest.raises(services.TicketScopeError):
        it_child.create_it_child_ticket(
            parent=stale_parent,
            summary="Must not cross office scope",
            technical_priority="P3",
            actor=actor,
        )

    assert set(Ticket.objects.values_list("id", flat=True)) == before_ids
    assert not TicketLink.objects.filter(to_ticket=stale_parent, kind="it_child").exists()


def test_child_creation_derives_copy_fields_from_canonical_locked_parent(
    basic_world,
) -> None:
    stale_parent = _parent(basic_world)
    other_office = Office.objects.create(
        region=basic_world["region"],
        code="IT-CHILD-FRESH",
        name="Fresh child office",
    )
    fresh_requester = Contact.objects.create(
        full_name="Fresh requester",
        email="fresh-requester@example.test",
    )
    Ticket.objects.filter(id=stale_parent.id).update(
        office=other_office,
        requester=fresh_requester,
        matter_reference="FRESH-MATTER",
    )
    actor = _office_actor(other_office, subject="fresh-office-agent")

    child = it_child.create_it_child_ticket(
        parent=stale_parent,
        summary="Use locked parent fields",
        technical_priority="P3",
        carry_matter_reference=True,
        actor=actor,
    )

    assert child.office == other_office
    assert child.requester == fresh_requester
    assert child.matter_reference == "FRESH-MATTER"


def test_resolving_child_rolls_back_when_locked_parent_sync_fails(basic_world) -> None:
    parent = _parent(basic_world)
    child = _create_child(parent, basic_world)
    validation = Status.objects.get(domain="it", code="validation")
    Ticket.objects.filter(id=child.id).update(status=validation)
    child.refresh_from_db()
    before_child_history = TransitionHistory.objects.filter(ticket=child).count()
    before_child_audits = AuditEvent.objects.filter(object_id=str(child.id)).count()
    before_child_outbox = OutboxEvent.objects.filter(aggregate_id=str(child.id)).count()
    before_child_custody = child.custody_events.count()
    before_parent_custody = parent.custody_events.count()

    with (
        patch(
            "apps.tickets.it_child.sync_slas_for_transition",
            side_effect=RuntimeError("parent SLA sync failed"),
        ),
        pytest.raises(RuntimeError, match="parent SLA sync failed"),
    ):
        services.transition_ticket(
            ticket_id=child.id,
            actor=_it_actor(),
            expected_updated_at=child.updated_at,
            to_status_code="resolved",
            resolution_code="FIXED",
            resolution_summary="Technical dependency fixed",
        )

    child.refresh_from_db()
    parent.refresh_from_db()
    assert child.status.code == "validation"
    assert child.resolution_code == ""
    assert child.resolved_at is None
    assert parent.status.code == "waiting_it"
    assert parent.waiting_reason == "Waiting for IT"
    assert TransitionHistory.objects.filter(ticket=child).count() == before_child_history
    assert AuditEvent.objects.filter(object_id=str(child.id)).count() == before_child_audits
    assert OutboxEvent.objects.filter(aggregate_id=str(child.id)).count() == before_child_outbox
    assert child.custody_events.count() == before_child_custody
    assert parent.custody_events.count() == before_parent_custody
