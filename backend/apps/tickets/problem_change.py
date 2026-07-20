"""Problem and Change management (P2 — wired in M6).

Problem: a cluster of related incidents. Change: a planned modification to a
service or system. Both are stored as Ticket records with a `kind` flag so
the same domain logic (numbering, status, SLA, scope) continues to work.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Ticket

logger = logging.getLogger(__name__)


class ProblemManager:
    """Operations for problem records and their incident links."""

    @staticmethod
    def open_problem(*, title: str, description: str, opened_by: str, related_incident_ids: list[str] | None = None) -> Ticket:
        from apps.catalogue.models import RequestType, Service
        from apps.contacts.models import Contact
        from apps.organisations.models import Office

        from .models import Ticket, TicketLink
        from .services import create_ticket

        # Open problems in IT domain
        service = Service.objects.filter(domain="it", code="IT-INC").first()
        request_type = RequestType.objects.filter(service=service, code="OUTAGE").first() if service else None
        office = Office.objects.filter(is_active=True).first()
        requester, _ = Contact.objects.get_or_create(
            email="problems@mhc.local",
            defaults={"full_name": "Problem Manager"},
        )
        ticket = create_ticket(
            domain="it",
            title=title,
            description=description,
            requester=requester,
            service=service,
            request_type=request_type,
            office=office,
            channel="internal",
            actor_subject=opened_by,
        )
        # Mark the ticket as a problem by hijacking tags (no schema change needed)
        ticket.tags = list(ticket.tags) + ["problem"]
        ticket.save(update_fields=["tags", "updated_at"])
        if related_incident_ids:
            for incident_id in related_incident_ids:
                try:
                    inc = Ticket.objects.get(id=incident_id)
                except Ticket.DoesNotExist:
                    continue
                TicketLink.objects.create(
                    from_ticket=inc, to_ticket=ticket, kind="blocks",
                )
        return ticket


class ChangeManager:
    """Planned change windows with risk and approval status."""

    @staticmethod
    def open_change(*, title: str, description: str, scheduled_at, risk: str, opened_by: str) -> Ticket:
        from apps.catalogue.models import RequestType, Service
        from apps.contacts.models import Contact
        from apps.organisations.models import Office

        from .services import create_ticket

        service = Service.objects.filter(domain="it", code="IT-INC").first()
        request_type = RequestType.objects.filter(service=service, code="OUTAGE").first() if service else None
        office = Office.objects.filter(is_active=True).first()
        requester, _ = Contact.objects.get_or_create(
            email="changes@mhc.local",
            defaults={"full_name": "Change Manager"},
        )
        ticket = create_ticket(
            domain="it",
            title=f"[Change][{risk}] {title}",
            description=description,
            requester=requester,
            service=service,
            request_type=request_type,
            office=office,
            channel="internal",
            actor_subject=opened_by,
        )
        ticket.custom_fields = {**ticket.custom_fields, "scheduled_at": scheduled_at.isoformat(), "risk": risk}
        ticket.tags = list(ticket.tags) + ["change", f"risk:{risk}"]
        ticket.save(update_fields=["custom_fields", "tags", "updated_at"])
        return ticket
