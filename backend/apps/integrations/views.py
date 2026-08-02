"""e-Estate reference validation stub (PRD §27.3).

The real implementation calls the e-Estate API. For P0 we ship an
in-process stub that:
  * records the external identifier
  * returns a minimal safe summary (matter number, status, parties)
  * never copies the case file
  * writes an audit event

The shape of the response mirrors what the real adapter will return so
the call site doesn't have to change when production goes live.
"""
from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity_access.models import User
from apps.identity_access.scope import scope_ticket_queryset
from apps.tickets.models import OutboxEvent, Ticket

# Simulated estate registry. In production this is an API call.
_FAKE_ESTATES = {
    "EST-2026-000123": {
        "matter_number": "EST-2026-000123",
        "deceased": "M. DLAMINI",
        "estate_type": "testate",
        "status": "letters_of_executorship_issued",
        "office": "MHC-MBA",
        "opened_at": "2026-01-15T09:00:00Z",
        "updated_at": "2026-05-30T11:30:00Z",
    },
    "EST-2025-000987": {
        "matter_number": "EST-2025-000987",
        "deceased": "N. NKOMO",
        "estate_type": "intestate",
        "status": "awaiting_inventory",
        "office": "MHC-MAN",
        "opened_at": "2025-11-02T08:00:00Z",
        "updated_at": "2026-04-12T14:15:00Z",
    },
}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def validate_matter(request: Request, ticket_number: str) -> Response:
    """Validate the matter reference on a ticket against the e-Estate stub."""
    if not isinstance(request.user, User):
        raise PermissionDenied(
            detail="Authentication credentials were not provided.",
            code="not_authenticated",
        )
    ticket = scope_ticket_queryset(
        request.user,
        Ticket.objects.all(),
        request=request,
    ).filter(number=ticket_number).first()
    if ticket is None:
        return Response({"detail": "ticket not found"}, status=404)
    ref = ticket.matter_reference
    if not ref:
        return Response({"status": "no_matter_reference", "ticket": ticket_number})
    summary = _FAKE_ESTATES.get(ref)
    if not summary:
        return Response({
            "status": "not_found",
            "reference": ref,
            "ticket": ticket_number,
        })
    OutboxEvent.objects.create(
        aggregate="ticket",
        aggregate_id=str(ticket.id),
        event_type="eestate.validated",
        payload={"matter_number": ref, "by": request.user.keycloak_subject},
    )
    return Response({
        "status": "found",
        "ticket": ticket_number,
        "reference": ref,
        "summary": {
            "matter_number": summary["matter_number"],
            "deceased_initial": " ".join(p[0] + "." for p in summary["deceased"].split()[1:]),
            "estate_type": summary["estate_type"],
            "status": summary["status"],
            "office": summary["office"],
            "updated_at": summary["updated_at"],
        },
    })
