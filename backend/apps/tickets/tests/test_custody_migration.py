"""Migration-level reconstruction tests for the custody ledger."""

from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest

from apps.audit.models import AuditEvent
from apps.catalogue.models import RequestType
from apps.identity_access.models import User
from apps.organisations.models import ServiceLocation
from apps.tickets.custody import verify_custody_chain
from apps.tickets.models import Ticket
from apps.workflow.models import Status, TransitionHistory

pytestmark = pytest.mark.django_db(transaction=True)


def _ticket(basic_world, *, number: str) -> Ticket:
    return Ticket.objects.create(
        number=number,
        domain="operational",
        title="Legacy custody history",
        status=Status.objects.get(domain="operational", code="new"),
        priority="P3",
        channel="web",
        requester=basic_world["contact"],
        service=basic_world["gen_info"],
        request_type=RequestType.objects.get(service=basic_world["gen_info"]),
        office=basic_world["office"],
    )


def _user(*, username: str, subject: str) -> User:
    return User.objects.create_user(
        username=username,
        password="not-used",
        keycloak_subject=subject,
        display_name=f"{username.title()} Agent",
    )


def _audit(
    *,
    ticket: Ticket,
    action: str,
    actor_subject: str,
    before: dict[str, object],
    after: dict[str, object],
    occurred_at: datetime,
) -> AuditEvent:
    event = AuditEvent.objects.create(
        actor_subject=actor_subject,
        action=action,
        object_type="ticket",
        object_id=str(ticket.id),
        payload={"before": before, "after": after},
        payload_hash="0" * 64,
    )
    AuditEvent.objects.filter(pk=event.pk).update(occurred_at=occurred_at)
    event.refresh_from_db()
    return event


def test_backfill_reconstructs_deterministic_verifiable_history(basic_world):
    """Dropping a source or changing sort order would alter this ledger."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    ticket = _ticket(basic_world, number="OP-LEGACY-BACKFILL-1")
    first = _user(username="first", subject="agent-first")
    second = _user(username="second", subject="agent-second")
    first_queue = ServiceLocation.objects.create(
        office=basic_world["office"], name="Legacy intake"
    )
    created_at = datetime(2025, 1, 2, 8, 0, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=created_at)
    _audit(
        ticket=ticket,
        action="ticket.created",
        actor_subject="intake-worker",
        before={},
        after={},
        occurred_at=created_at,
    )
    _audit(
        ticket=ticket,
        action="ticket.assignment.changed",
        actor_subject="supervisor",
        before={"assignee": None},
        after={"assignee": str(first.id)},
        occurred_at=created_at + timedelta(minutes=1),
    )
    _audit(
        ticket=ticket,
        action="ticket.work_state.changed",
        actor_subject="supervisor",
        before={"queue": None},
        after={"queue": str(first_queue.id)},
        occurred_at=created_at + timedelta(minutes=2),
    )
    _audit(
        ticket=ticket,
        action="ticket.assignment.changed",
        actor_subject="supervisor",
        before={"assignee": str(first.id)},
        after={"assignee": str(second.id)},
        occurred_at=created_at + timedelta(minutes=3),
    )
    closed = Status.objects.get(domain="operational", code="closed")
    transition = TransitionHistory.objects.create(
        ticket=ticket,
        from_status=ticket.status,
        to_status=closed,
        actor_subject="agent-second",
        reason="Resolved legacy ticket",
    )
    TransitionHistory.objects.filter(pk=transition.pk).update(
        occurred_at=created_at + timedelta(minutes=4)
    )

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)
    backfill_ticket_custody(django_apps, None)

    assert list(ticket.custody_events.values_list("event_type", flat=True)) == [
        "created",
        "assigned",
        "queue_changed",
        "reassigned",
        "closed",
    ]
    assert ticket.custody_events.count() == 5
    created, assigned, queue_changed, reassigned, closed_event = ticket.custody_events.all()
    assert created.new_status == {"code": "new", "label": "New"}
    assert assigned.new_owner == {
        "id": str(first.id),
        "subject": "agent-first",
        "display_name": "First Agent",
    }
    assert queue_changed.new_queue == {"id": str(first_queue.id), "label": "Legacy intake"}
    assert reassigned.previous_owner["id"] == str(first.id)
    assert reassigned.new_owner["id"] == str(second.id)
    assert closed_event.new_status == {"code": "closed", "label": "Closed"}
    assert verify_custody_chain(ticket) is True


def test_backfill_synthesizes_only_a_minimal_legacy_created_event(basic_world):
    """A missing creation audit must not fabricate ownership or routing facts."""
    backfill_ticket_custody = import_module(
        "apps.tickets.migrations.0006_backfill_ticket_custody"
    ).backfill_ticket_custody
    ticket = _ticket(basic_world, number="OP-LEGACY-BACKFILL-2")
    created_at = datetime(2025, 1, 3, 8, 0, tzinfo=UTC)
    Ticket.objects.filter(pk=ticket.pk).update(created_at=created_at)

    from django.apps import apps as django_apps

    backfill_ticket_custody(django_apps, None)

    event = ticket.custody_events.get()
    assert event.event_type == "created"
    assert event.occurred_at == created_at
    assert (event.actor_kind, event.actor_subject) == ("system", "legacy-backfill")
    assert event.previous_owner is None
    assert event.new_owner is None
    assert event.previous_queue is None
    assert event.new_queue is None
    assert verify_custody_chain(ticket) is True
