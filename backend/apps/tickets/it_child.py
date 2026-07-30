"""IT child-ticket pattern (PRD §11.4).

The Operational agent identifies a technical dependency and opens a
sanitised IT child ticket. Only selected fields and explicitly authorised
attachments are copied. IT cannot see the parent message body or
attachments by default. Status summaries sync back to the parent without
exposing the IT child to the requester.
"""
from __future__ import annotations

import logging

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from rest_framework.request import Request

from apps.catalogue.models import RequestType, Service
from apps.identity_access.models import User
from apps.identity_access.scope import (
    AuthoritySnapshot,
    get_authority_snapshot,
    scope_ticket_queryset,
)
from apps.sla.services import sync_slas_for_transition
from apps.workflow.models import Status, TransitionHistory

from .custody import (
    CustodyActor,
    CustodyEventInput,
    queue_snapshot,
    status_snapshot,
    user_actor,
)
from .events import record_ticket_event
from .models import Ticket, TicketLink
from .permissions import can_add_ticket_content
from .services import TicketPermissionError, TicketScopeError, link_tickets

logger = logging.getLogger(__name__)


# Fields that may be carried over from the operational parent to the IT child
# when the agent creates a child ticket. Anything not listed here stays in the
# operational parent and is invisible to the IT domain.
SANITISED_CARRY_OVER = {
    "office",            # the office that needs the technical work
    "matter_reference",  # limited identifier; agent must authorise
}


def _resolve_it_service_and_type() -> tuple[Service, RequestType]:
    """Pick a default IT service + request type. The operational agent can
    override these in the UI; for the smoke path we use the seeded values."""
    service = Service.objects.filter(domain="it", code="IT-INC").first()
    if not service:
        service = Service.objects.create(
            code="IT-INC", name="IT incident report", domain="it", is_active=True,
        )
    request_type = RequestType.objects.filter(service=service, code="OUTAGE").first()
    if not request_type:
        request_type = RequestType.objects.create(
            service=service, code="OUTAGE", name="System outage",
            default_priority="P2",
        )
    return service, request_type


@transaction.atomic
def create_it_child_ticket(
    *,
    parent: Ticket,
    summary: str,
    technical_priority: str,
    actor: User,
    request: Request | None = None,
    snapshot: AuthoritySnapshot | None = None,
    carry_matter_reference: bool = False,
) -> Ticket:
    """Create a sanitised IT child ticket linked to an operational parent.

    Rules enforced here (PRD §11.4):
      1. Only selected fields and zero attachments by default
      2. Parent remains owned by the operational team
      3. IT child lives in the IT domain with its own status, owner, queue
      4. IT cannot read the parent's message body or attachments
      5. The link is auditable
    """
    authority = snapshot or get_authority_snapshot(actor, request=request)
    try:
        parent = (
            scope_ticket_queryset(
                actor,
                Ticket.objects.select_for_update(of=("self",)),
                snapshot=authority,
            )
            .select_related("status", "office", "requester")
            .get(id=parent.id)
        )
    except Ticket.DoesNotExist as exc:
        raise TicketScopeError from exc
    if not can_add_ticket_content(actor, parent, request=request):
        raise TicketPermissionError
    if parent.domain != "operational":
        raise ValueError("IT child can only be created from an operational parent")
    if parent.status.is_terminal or parent.status.code in {
        "resolved",
        "cancelled",
        "rejected",
    }:
        raise ValueError("IT child cannot be created from a terminal parent")
    if not summary.strip():
        raise ValueError("A sanitised summary is required for the IT child")

    service, request_type = _resolve_it_service_and_type()
    initial_status = Status.objects.get(domain="it", code="new")
    requester = parent.requester
    office = parent.office

    # Find next IT number
    from .services import next_ticket_number
    number = next_ticket_number("it")

    child = Ticket.objects.create(
        number=number,
        domain="it",
        title=summary.strip()[:255],
        description="",  # the operational parent's body is never copied
        status=initial_status,
        priority=technical_priority,
        channel="internal",
        source_account=actor.keycloak_subject,
        requester=requester,  # the same requester for context; agent can override
        service=service,
        request_type=request_type,
        office=office,
        matter_reference=parent.matter_reference if carry_matter_reference else "",
        confidentiality="sensitive",
    )

    event_actor = actor.keycloak_subject
    record_ticket_event(
        ticket=child,
        actor_subject=event_actor,
        action="ticket.created",
        before={},
        after={
            "domain": "it",
            "channel": "internal",
            "priority": technical_priority,
            "requester_id": str(requester.id),
            "title": child.title,
        },
        metadata={"source": "it-child", "parent_ticket_number": parent.number},
        custody_actor=user_actor(actor),
        custody_events=(
            CustodyEventInput.created(
                source_process="ticket.it_child.create",
                new_queue=queue_snapshot(child.queue),
                new_status=status_snapshot(initial_status),
            ),
        ),
    )
    link_tickets(
        source=child,
        target=parent,
        kind="it_child",
        actor_subject=event_actor,
        metadata={"source": "it-child"},
    )

    # Mark the operational parent as Waiting for IT
    waiting_it = Status.objects.filter(domain="operational", code="waiting_it").first()
    if waiting_it and parent.status.code not in ("closed", "resolved", "cancelled", "rejected"):
        previous = parent.status
        previous_waiting_reason = parent.waiting_reason
        parent.status = waiting_it
        parent.waiting_reason = "Waiting for IT"
        parent.save(update_fields=["status", "waiting_reason", "updated_at"])
        sync_slas_for_transition(
            ticket=parent,
            from_code=previous.code,
            to_code=waiting_it.code,
            actor_subject=event_actor,
        )
        history = TransitionHistory.objects.create(
            ticket=parent,
            from_status=previous,
            to_status=waiting_it,
            actor_subject=event_actor,
            reason=f"IT child ticket {child.number} created",
        )
        record_ticket_event(
            ticket=parent,
            actor_subject=event_actor,
            action="ticket.transitioned",
            before={
                "status": previous.code,
                "waiting_reason": previous_waiting_reason,
            },
            after={
                "status": waiting_it.code,
                "waiting_reason": "Waiting for IT",
            },
            metadata={
                "source": "it-child",
                "child_ticket_number": child.number,
            },
            custody_actor=user_actor(actor),
            custody_events=(
                CustodyEventInput(
                    event_type="status_changed",
                    source_process="ticket.it_child.create",
                    source_record_type="workflow_transition",
                    source_record_id=str(history.id),
                    previous_queue=queue_snapshot(parent.queue),
                    new_queue=queue_snapshot(parent.queue),
                    previous_status=status_snapshot(previous),
                    new_status=status_snapshot(waiting_it),
                    reason=f"IT child ticket {child.number} created",
                    occurred_at=history.occurred_at,
                ),
            ),
        )
    return child


@transaction.atomic
def sync_child_status_to_parent(*, child: Ticket, actor_subject: str = "") -> None:
    """Push a safe status summary from the IT child to the operational parent.

    Allowed parent state transitions driven by the child:
      * child resolved/closed -> parent moves from waiting_it to in_progress
        (operational agent verifies the outcome before closing the parent)
    """
    child = (
        Ticket.objects.select_for_update(of=("self",))
        .select_related("status")
        .get(id=child.id)
    )
    if child.domain != "it" or child.status.code not in {"resolved", "closed"}:
        return
    parent_id = TicketLink.objects.filter(
        from_ticket=child,
        kind="it_child",
    ).values_list("to_ticket_id", flat=True).first()
    if parent_id is None:
        return
    parent = (
        Ticket.objects.select_for_update(of=("self",))
        .select_related("status")
        .get(id=parent_id)
    )
    if parent.status.code not in ("waiting_it",):
        return  # parent isn't waiting on IT; nothing to sync
    target_code = "in_progress"
    target = Status.objects.filter(domain="operational", code=target_code).first()
    if not target:
        raise ImproperlyConfigured("Missing operational in_progress status.")
    previous = parent.status
    previous_waiting_reason = parent.waiting_reason
    parent.status = target
    parent.waiting_reason = ""
    parent.save(update_fields=["status", "waiting_reason", "updated_at"])
    event_actor = actor_subject or "it-child-sync"
    sync_slas_for_transition(
        ticket=parent,
        from_code=previous.code,
        to_code=target.code,
        actor_subject=event_actor,
    )
    history = TransitionHistory.objects.create(
        ticket=parent,
        from_status=previous,
        to_status=target,
        actor_subject=event_actor,
        reason=f"IT child {child.number} returned: {child.status.name}",
    )
    record_ticket_event(
        ticket=parent,
        actor_subject=event_actor,
        action="ticket.transitioned",
        before={
            "status": previous.code,
            "waiting_reason": previous_waiting_reason,
        },
        after={"status": target.code, "waiting_reason": ""},
        metadata={
            "source": "it-child-sync",
            "child_ticket_number": child.number,
            "child_status": child.status.code,
        },
        custody_actor=CustodyActor.system(
            "it-child-sync",
            "IT child status synchronisation",
        ),
        custody_events=(
            CustodyEventInput(
                event_type="status_changed",
                source_process="ticket.it_child.sync",
                source_record_type="workflow_transition",
                source_record_id=str(history.id),
                previous_queue=queue_snapshot(parent.queue),
                new_queue=queue_snapshot(parent.queue),
                previous_status=status_snapshot(previous),
                new_status=status_snapshot(target),
                reason=f"IT child {child.number} returned: {child.status.name}",
                occurred_at=history.occurred_at,
            ),
        ),
    )
