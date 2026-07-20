"""IT child-ticket pattern (PRD §11.4).

The Operational agent identifies a technical dependency and opens a
sanitised IT child ticket. Only selected fields and explicitly authorised
attachments are copied. IT cannot see the parent message body or
attachments by default. Status summaries sync back to the parent without
exposing the IT child to the requester.
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.catalogue.models import RequestType, Service
from apps.contacts.models import Contact
from apps.organisations.models import Office
from apps.workflow.models import Status, TransitionHistory

from .models import OutboxEvent, Ticket, TicketLink

logger = logging.getLogger(__name__)


# Fields that may be carried over from the operational parent to the IT child
# when the agent creates a child ticket. Anything not listed here stays in the
# operational parent and is invisible to the IT domain.
SANITISED_CARRY_OVER = {
    "office",            # the office that needs the technical work
    "matter_reference",  # limited identifier; agent must authorise
}


def _resolve_it_service_and_type():
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
    requester: Contact,
    requester_office: Office,
    technical_priority: str,
    carry_matter_reference: bool = False,
    actor_subject: str = "",
) -> Ticket:
    """Create a sanitised IT child ticket linked to an operational parent.

    Rules enforced here (PRD §11.4):
      1. Only selected fields and zero attachments by default
      2. Parent remains owned by the operational team
      3. IT child lives in the IT domain with its own status, owner, queue
      4. IT cannot read the parent's message body or attachments
      5. The link is auditable
    """
    if parent.domain != "operational":
        raise ValueError("IT child can only be created from an operational parent")
    if not summary.strip():
        raise ValueError("A sanitised summary is required for the IT child")

    service, request_type = _resolve_it_service_and_type()
    initial_status = Status.objects.get(domain="it", code="new")
    office = requester_office or parent.office

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
        source_account=actor_subject or "operational-parent",
        requester=requester,  # the same requester for context; agent can override
        service=service,
        request_type=request_type,
        office=office,
        matter_reference=parent.matter_reference if carry_matter_reference else "",
        confidentiality="sensitive",
    )

    TicketLink.objects.create(
        from_ticket=child, to_ticket=parent, kind="it_child",
    )

    OutboxEvent.objects.create(
        aggregate="ticket",
        aggregate_id=str(child.id),
        event_type="ticket.it_child_created",
        payload={
            "parent_number": parent.number,
            "child_number": child.number,
            "actor": actor_subject,
        },
    )

    # Mark the operational parent as Waiting for IT
    waiting_it = Status.objects.filter(domain="operational", code="waiting_it").first()
    if waiting_it and parent.status.code not in ("closed", "resolved", "cancelled", "rejected"):
        previous = parent.status
        parent.status = waiting_it
        parent.waiting_reason = "Waiting for IT"
        parent.save(update_fields=["status", "waiting_reason", "updated_at"])
        TransitionHistory.objects.create(
            ticket=parent,
            from_status=previous,
            to_status=waiting_it,
            actor_subject=actor_subject or "system",
            reason=f"IT child ticket {child.number} created",
        )
    return child


def sync_child_status_to_parent(*, child: Ticket, actor_subject: str = "") -> None:
    """Push a safe status summary from the IT child to the operational parent.

    Allowed parent state transitions driven by the child:
      * child resolved/closed -> parent moves from waiting_it to in_progress
        (operational agent verifies the outcome before closing the parent)
    """
    if child.domain != "it":
        return
    link = TicketLink.objects.filter(from_ticket=child, kind="it_child").first()
    if not link:
        return
    parent = link.to_ticket
    if parent.status.code not in ("waiting_it",):
        return  # parent isn't waiting on IT; nothing to sync
    target_code = "in_progress"
    target = Status.objects.filter(domain="operational", code=target_code).first()
    if not target:
        return
    previous = parent.status
    parent.status = target
    parent.waiting_reason = ""
    parent.save(update_fields=["status", "waiting_reason", "updated_at"])
    TransitionHistory.objects.create(
        ticket=parent,
        from_status=previous,
        to_status=target,
        actor_subject=actor_subject or "it-child-sync",
        reason=f"IT child {child.number} returned: {child.status.name}",
    )
