"""Ticket API views.

Authorisation is server-side: a user must have a scope that matches the
ticket's domain. The frontend never gets to decide what to show.
"""
from __future__ import annotations

import logging

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.contacts.models import Contact
from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.pagination import TicketCursorPagination
from apps.identity_access.scope import (
    ScopePermission,
    attach_scopes,
    has_unrestricted_domain_scope,
    public_endpoint,
    scope_ticket_queryset,
)
from apps.sla.models import SlaPolicy
from apps.sla.services import instantiate_slas

from . import services
from .api import (
    MessageCreateSerializer,
    NoteCreateSerializer,
    PublicIntakeSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
    TransitionRequestSerializer,
)
from .models import Ticket

logger = logging.getLogger(__name__)


class PublicIntakeThrottle(AnonRateThrottle):
    """Tight throttle for the public web form (FR-073 abuse protection)."""
    scope = "public_intake"


class TicketViewSet(viewsets.ModelViewSet):
    """CRUD + transition endpoints for tickets."""

    queryset = Ticket.objects.select_related(
        "status", "requester", "service", "request_type", "office", "assignee"
    ).all()
    authentication_classes = [KeycloakJWTAuthentication]
    permission_classes = [IsAuthenticated, ScopePermission]
    lookup_field = "number"
    lookup_value_regex = "[A-Z]{2}-\\d{6}-\\d{6}"
    pagination_class = TicketCursorPagination

    def get_serializer_class(self):
        if self.action in ("retrieve", "transition", "messages", "notes", "links"):
            return TicketDetailSerializer
        return TicketListSerializer

    def get_queryset(self):
        return scope_ticket_queryset(
            self.request.user,
            super().get_queryset(),
            request=self.request,
        ).order_by("priority", "-created_at", "-id")

    def filter_queryset(self, queryset):
        qs = super().filter_queryset(queryset)
        params = self.request.query_params
        if "status" in params:
            qs = qs.filter(status__code=params["status"])
        if "priority" in params:
            qs = qs.filter(priority=params["priority"])
        if "assignee" in params:
            qs = qs.filter(assignee__username=params["assignee"])
        if "office" in params:
            qs = qs.filter(office__code=params["office"])
        if "channel" in params:
            qs = qs.filter(channel=params["channel"])
        if "search" in params:
            qs = qs.filter(
                Q(number__icontains=params["search"])
                | Q(title__icontains=params["search"])
                | Q(matter_reference__icontains=params["search"])
            )
        return qs

    @action(detail=True, methods=["post"])
    def transition(self, request, number=None):
        ticket = self.get_object()
        serializer = TransitionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.transition_ticket(
                ticket=ticket,
                to_status_code=serializer.validated_data["to_status"],
                actor_subject=request.user.keycloak_subject,
                reason=serializer.validated_data.get("reason", ""),
                resolution_code=serializer.validated_data.get("resolution_code", ""),
                resolution_summary=serializer.validated_data.get("resolution_summary", ""),
            )
        except services.TransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        # If an IT child reaches resolved, sync parent from waiting_it -> in_progress
        if ticket.domain == "it" and ticket.status.code == "resolved":
            from .it_child import sync_child_status_to_parent
            sync_child_status_to_parent(child=ticket, actor_subject=request.user.keycloak_subject)
        return Response(TicketDetailSerializer(ticket).data)

    @action(detail=True, methods=["get", "post"], url_path="messages")
    def messages(self, request, number=None):
        ticket = self.get_object()
        if request.method == "GET":
            from .api import TicketMessageSerializer

            return Response({
                "results": TicketMessageSerializer(ticket.messages.all(), many=True).data
            })
        ser = MessageCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        msg = services.add_message(
            ticket=ticket,
            direction="outbound",
            author_subject=request.user.keycloak_subject,
            author_label=request.user.display_name or request.user.username,
            body_text=ser.validated_data["body_text"],
            body_html=ser.validated_data.get("body_html", ""),
            template_key=ser.validated_data.get("template_key", ""),
            template_version=ser.validated_data.get("template_version", ""),
        )
        # Mark first response if applicable
        if ticket.first_responded_at is None and ticket.requester:
            from django.utils import timezone
            ticket.first_responded_at = timezone.now()
            ticket.save(update_fields=["first_responded_at", "updated_at"])
        return Response({"id": str(msg.id)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="notes")
    def notes(self, request, number=None):
        ticket = self.get_object()
        if request.method == "GET":
            from .api import TicketNoteSerializer
            return Response({"results": TicketNoteSerializer(ticket.notes.all(), many=True).data})
        ser = NoteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        note = services.add_internal_note(
            ticket=ticket,
            body=ser.validated_data["body"],
            author_subject=request.user.keycloak_subject,
        )
        return Response({"id": str(note.id)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="it-child")
    def it_child(self, request, number=None):
        """Create a sanitised IT child ticket from this operational parent.

        Body: {"summary": "...", "technical_priority": "P1|P2|P3|P4",
               "carry_matter_reference": true|false}
        """
        from .it_child import create_it_child_ticket
        parent = self.get_object()
        if parent.domain != "operational":
            return Response(
                {"detail": "IT children can only be created from operational parents."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        body = request.data or {}
        summary = (body.get("summary") or "").strip()
        if not summary:
            return Response({"detail": "summary is required"}, status=status.HTTP_400_BAD_REQUEST)
        priority = body.get("technical_priority") or "P3"
        carry = bool(body.get("carry_matter_reference", True))
        try:
            child = create_it_child_ticket(
                parent=parent,
                summary=summary,
                requester=parent.requester,
                requester_office=parent.office,
                technical_priority=priority,
                carry_matter_reference=carry,
                actor_subject=request.user.keycloak_subject,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "child_number": child.number,
                "child_id": str(child.id),
                "domain": child.domain,
                "priority": child.priority,
                "status": child.status.code,
                "parent_number": parent.number,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="kanban")
    def kanban(self, request):
        """Return tickets grouped by status, ready for the Kanban view."""
        attach_scopes(request)
        qs = self.get_queryset()
        params = request.query_params
        if "domain" in params:
            qs = qs.filter(domain=params["domain"])
        # Exclude terminal and out-of-office
        from apps.workflow.models import Status
        terminal = Status.objects.filter(is_terminal=True).values_list("code", flat=True)
        qs = qs.exclude(status__code__in=list(terminal))
        grouped: dict[str, list] = {}
        from .api import TicketListSerializer
        for ticket in qs.order_by("priority", "-created_at")[:300]:
            code = ticket.status.code
            grouped.setdefault(code, []).append(TicketListSerializer(ticket).data)
        return Response({"columns": grouped})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([PublicIntakeThrottle])
@public_endpoint
def public_intake(request):
    """Public web form intake — creates a ticket and returns its number.

    Rate-limited by ``PublicIntakeThrottle`` (5/min per IP).
    No authentication required.
    """
    import bleach

    from apps.catalogue.models import RequestType, Service
    from apps.organisations.models import Office

    ip = request.META.get("REMOTE_ADDR", "unknown")
    ser = PublicIntakeSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data

    if not data.get("consent"):
        return Response(
            {"detail": "Consent is required to submit a request."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        service = Service.objects.get(code=data["service_code"], domain="operational")
        request_type = RequestType.objects.get(service=service, code=data["request_type_code"])
        office = Office.objects.get(code=data["office_code"])
    except (Service.DoesNotExist, RequestType.DoesNotExist, Office.DoesNotExist) as exc:
        return Response({"detail": "Invalid service or office.", "code": str(exc)},
                        status=status.HTTP_400_BAD_REQUEST)

    # Create or update requester contact
    contact_kwargs = {"full_name": data["requester_name"]}
    if data.get("requester_email"):
        contact_kwargs["email"] = data["requester_email"]
    if data.get("requester_phone"):
        contact_kwargs["phone_e164"] = data["requester_phone"]
    contact = None
    if data.get("requester_email"):
        contact, _ = Contact.objects.get_or_create(
            email=data["requester_email"], defaults=contact_kwargs
        )
        # refresh derived fields
        updated = False
        if contact.full_name != data["requester_name"]:
            contact.full_name = data["requester_name"]
            updated = True
        if data.get("requester_phone") and contact.phone_e164 != data["requester_phone"]:
            contact.phone_e164 = data["requester_phone"]
            updated = True
        if updated:
            contact.save()
    else:
        contact = Contact.objects.create(**contact_kwargs)

    ticket = services.create_ticket(
        domain="operational",
        title=bleach.clean(data["title"], strip=True)[:255],
        description=bleach.clean(data["description"], strip=True),
        requester=contact,
        service=service,
        request_type=request_type,
        office=office,
        channel=data.get("channel") or "web",
        matter_reference=data.get("matter_reference", ""),
        actor_subject="public-form",
        ip_address=ip,
    )

    # Materialise SLA instances
    try:
        policy = SlaPolicy.objects.get(
            domain="operational",
            priority=ticket.priority,
            is_active=True,
        )
        instantiate_slas(ticket=ticket, policy=policy)
    except SlaPolicy.DoesNotExist:
        logger.warning("no_sla_policy_for_ticket", extra={"correlation_id": ticket.number})

    return Response(
        {
            "ticket_number": ticket.number,
            "domain": ticket.domain,
            "title": ticket.title,
            "priority": ticket.priority,
            "message": "Your request has been received. Keep this number for your records.",
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, ScopePermission])
def operational_dashboard(request):
    """Essential operational dashboard data for the M2 milestone.

    Restricted to authenticated users with an operational scope. IT-only
    users must not see this; the cross-domain guard is enforced by an
    explicit unrestricted-domain check.
    """
    attach_scopes(request)
    if not has_unrestricted_domain_scope(
        request.user,
        "operational",
        request=request,
    ):
        return Response(
            {"detail": "Operational scope required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone

    qs = scope_ticket_queryset(
        request.user,
        Ticket.objects.all(),
        request=request,
    ).filter(domain="operational")
    now = timezone.now()

    return Response({
        "totals": {
            "open": qs.exclude(status__code__in=[
                "closed",
                "resolved",
                "cancelled",
                "rejected",
                "duplicate",
                "spam",
            ]).count(),
            "today": qs.filter(created_at__date=now.date()).count(),
            "this_week": qs.filter(created_at__gte=now - timedelta(days=7)).count(),
        },
        "by_priority": list(
            qs.values("priority").annotate(count=Count("id")).order_by("priority")
        ),
        "by_status": list(
            qs.values("status__code", "status__name")
            .annotate(count=Count("id"))
            .order_by("status__order")
        ),
        "unassigned": qs.filter(assignee__isnull=True).exclude(
            status__code__in=["closed", "resolved", "cancelled", "rejected", "duplicate", "spam"]
        ).count(),
        "breached_sla": qs.filter(sla_instances__state="breached").distinct().count(),
    })
