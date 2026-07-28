"""Contact API views."""
from __future__ import annotations

import hashlib

from django.db.models import QuerySet
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.scope import ScopePermission
from apps.tickets.api import TicketMessageSerializer
from apps.tickets.models import Ticket
from apps.tickets.services import add_message

from .api import ContactCreateSerializer, ContactSerializer
from .models import Contact, VerificationToken


class ContactViewSet(viewsets.ModelViewSet[Contact]):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    authentication_classes = [KeycloakJWTAuthentication]
    permission_classes = [IsAuthenticated, ScopePermission]

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Contact]]:
        if self.action == "create":
            return ContactCreateSerializer
        return ContactSerializer

    def get_queryset(self) -> QuerySet[Contact]:
        qs = super().get_queryset()
        params = self.request.query_params
        if "search" in params:
            from django.db.models import Q
            term = params["search"]
            qs = qs.filter(
                Q(full_name__icontains=term)
                | Q(email__icontains=term)
                | Q(phone_e164__icontains=term)
            )
        return qs.order_by("full_name")[:100]

    @action(detail=False, methods=["get"], url_path="duplicates")
    def duplicates(self, request: Request) -> Response:
        """Suggest possible duplicate contacts (FR-007) without merging."""
        from django.db.models import Q
        params = request.query_params
        email = params.get("email", "").strip()
        phone = params.get("phone", "").strip()
        name = params.get("name", "").strip()
        qs = Contact.objects.none()
        if email:
            qs = qs | Contact.objects.filter(email__iexact=email)
        if phone:
            qs = qs | Contact.objects.filter(phone_e164=phone)
        if name:
            qs = qs | Contact.objects.filter(full_name__icontains=name)
        return Response({"results": ContactSerializer(qs.distinct()[:10], many=True).data})


# --- Requester-facing magic-link endpoints (FR-071/073/075) -----------------


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@api_view(["GET"])
@permission_classes([AllowAny])
def requester_status(request: Request, token: str) -> Response:
    """Public ticket status / history. Requires a valid token."""
    h = _hash(token)
    vt = VerificationToken.objects.filter(token_hash=h).first()
    if not vt or not vt.is_valid():
        return Response(
            {"detail": "Link is invalid or has expired."},
            status=status.HTTP_404_NOT_FOUND,
        )
    ticket = (
        Ticket.objects.filter(requester=vt.contact)
        .order_by("-created_at")
        .first()
    )
    if ticket is None:
        return Response(
            {"detail": "Link is invalid or has expired."},
            status=status.HTTP_404_NOT_FOUND,
        )
    safe_messages = [
        m for m in ticket.messages.all() if m.direction in ("outbound", "inbound")
    ]
    return Response({
        "ticket_number": ticket.number,
        "title": ticket.title,
        "status": ticket.status.public_label or ticket.status.name,
        "domain": ticket.domain,
        "priority": ticket.priority,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "messages": TicketMessageSerializer(safe_messages, many=True).data,
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def requester_reply(request: Request, token: str) -> Response:
    """Public reply from a verified requester (FR-075)."""
    h = _hash(token)
    vt = VerificationToken.objects.filter(token_hash=h).first()
    if not vt or not vt.is_valid():
        return Response(
            {"detail": "Link is invalid or has expired."},
            status=status.HTTP_404_NOT_FOUND,
        )
    body = (request.data or {}).get("body_text", "").strip()
    if not body:
        return Response({"detail": "body_text is required"}, status=status.HTTP_400_BAD_REQUEST)
    ticket = (
        Ticket.objects.filter(requester=vt.contact)
        .order_by("-created_at")
        .first()
    )
    if ticket is None:
        return Response(
            {"detail": "Link is invalid or has expired."},
            status=status.HTTP_404_NOT_FOUND,
        )
    msg = add_message(
        ticket=ticket,
        direction="inbound",
        actor_subject=vt.contact.email or "requester",
        author_subject=vt.contact.email or "requester",
        author_label=vt.contact.full_name,
        body_text=body,
    )
    return Response({"id": str(msg.id)}, status=status.HTTP_201_CREATED)
