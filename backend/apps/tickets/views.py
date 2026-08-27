"""Ticket API views.

Authorisation is server-side: a user must have a scope that matches the
ticket's domain. The frontend never gets to decide what to show.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import Never, Protocol, runtime_checkable

from django.db.models import Q, QuerySet
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.contacts.models import Contact
from apps.identity_access.authentication import KeycloakJWTAuthentication
from apps.identity_access.models import User
from apps.identity_access.pagination import TicketCursorPagination
from apps.identity_access.scope import (
    Scope,
    ScopePermission,
    attach_scopes,
    has_unrestricted_domain_scope,
    scope_ticket_queryset,
)
from apps.sla.models import SlaPolicy
from apps.sla.services import instantiate_slas

from . import services
from .activity import build_ticket_activity
from .api import (
    AssigneeSearchSerializer,
    AssignmentReceiptSerializer,
    AssignmentRequestSerializer,
    MessageCreateSerializer,
    NoteCreateSerializer,
    PublicIntakeSerializer,
    QueueRoutingRequestSerializer,
    RoutingReceiptSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
    TicketTrackingLookupSerializer,
    TicketTrackingSerializer,
    TransitionRequestSerializer,
    WorkStateRequestSerializer,
)
from .assignment import assign_ticket, route_ticket
from .eligibility import (
    AssigneeCandidate,
    eligible_assignees,
    eligible_escalation_supervisors,
)
from .models import Ticket
from .permissions import can_add_ticket_content, can_assign
from .tracking import build_tracking_projection, tracking_status_for
from .workflow import available_transitions

logger = logging.getLogger(__name__)


@runtime_checkable
class _TextCleaner(Protocol):
    def __call__(self, text: str, *, strip: bool) -> str: ...


def _clean_public_text(text: str) -> str:
    """Call Bleach through one checked boundary without importing untyped APIs."""
    cleaner: object = getattr(import_module("bleach"), "clean", None)
    if not isinstance(cleaner, _TextCleaner):
        raise RuntimeError("Bleach text cleaning is unavailable.")
    return cleaner(text, strip=True)


def _authenticated_user(request: Request) -> User:
    """Narrow the authenticated DRF principal to the local staff model."""
    if isinstance(request.user, User):
        return request.user
    raise PermissionDenied(
        detail="Authentication credentials were not provided.",
        code="not_authenticated",
    )


def _ticket_action_error(
    request: Request,
    *,
    code: str,
    detail: str,
    fields: Mapping[str, Sequence[str]],
    response_status: int,
) -> Response:
    return Response(
        {
            "code": code,
            "detail": detail,
            "fields": fields,
            "correlation_id": getattr(request, "correlation_id", ""),
        },
        status=response_status,
    )


def _serializer_error_fields(
    errors: Mapping[str, Sequence[object]],
) -> dict[str, list[str]]:
    return {field: [str(message) for message in messages] for field, messages in errors.items()}


def _candidate_payload(candidate: AssigneeCandidate) -> dict[str, object]:
    return {
        "id": str(candidate.id),
        "username": candidate.username,
        "display_name": candidate.display_name,
        "designations": list(candidate.designations),
        "team_labels": list(candidate.team_labels),
        "role_summaries": list(candidate.role_summaries),
    }


class TicketViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[Ticket],
):
    """Scoped ticket reads and explicit lifecycle-safe ticket actions."""

    queryset = Ticket.objects.select_related(
        "status", "requester", "service", "request_type", "office", "assignee"
    ).all()
    authentication_classes = [KeycloakJWTAuthentication]
    permission_classes = [IsAuthenticated, ScopePermission]
    lookup_field = "number"
    lookup_value_regex = "[A-Z][0-9]{5}|[A-Z][A-Z0-9]{1,7}-[0-9]{6}-[0-9]{6}"
    pagination_class = TicketCursorPagination

    def permission_denied(
        self,
        request: Request,
        message: str | None = None,
        code: str | None = None,
    ) -> Never:
        if (
            self.action in {"transition", "work_state", "assignment", "routing"}
            and request.user.is_authenticated
        ):
            raise PermissionDenied(
                detail="You cannot perform this ticket action.",
                code="ticket_action_forbidden",
            )
        super().permission_denied(request, message=message, code=code)

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Ticket]]:
        if self.action in (
            "retrieve",
            "transition",
            "messages",
            "notes",
            "links",
            "work_state",
            "assignees",
            "assignment",
            "routing",
            "activity",
        ):
            return TicketDetailSerializer
        return TicketListSerializer

    def get_queryset(self) -> QuerySet[Ticket]:
        return scope_ticket_queryset(
            self.request.user,
            super().get_queryset(),
            request=self.request,
        ).order_by("priority", "-created_at", "-id")

    def filter_queryset(self, queryset: QuerySet[Ticket]) -> QuerySet[Ticket]:
        qs = super().filter_queryset(queryset)
        params = self.request.query_params
        if "domain" in params:
            domain_field = serializers.ChoiceField(choices=Ticket.Domain.values)
            try:
                domain = domain_field.run_validation(params["domain"])
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"domain": exc.detail}) from exc
            qs = qs.filter(domain=domain)
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
        if "search" in params and self.action not in {
            "assignees",
            "escalation_supervisors",
        }:
            qs = qs.filter(
                Q(number__icontains=params["search"])
                | Q(title__icontains=params["search"])
                | Q(matter_reference__icontains=params["search"])
            )
        return qs

    @action(detail=False, methods=["get"], url_path="tracking")
    def tracking(self, request: Request) -> Response:
        lookup = TicketTrackingLookupSerializer(data=request.query_params)
        if not lookup.is_valid():
            return _ticket_action_error(
                request,
                code="invalid_ticket_reference",
                detail="Enter a valid ticket reference.",
                fields=_serializer_error_fields(lookup.errors),
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ticket = (
                self.get_queryset()
                .select_related("status", "office", "service")
                .get(number__iexact=lookup.validated_data["reference"])
            )
        except Ticket.DoesNotExist as exc:
            raise NotFound("Ticket not found.") from exc

        projection = build_tracking_projection(ticket)
        payload = {
            "reference": ticket.number,
            "title": ticket.title,
            "tracking_status": tracking_status_for(ticket.status),
            "status_updated_at": projection["status_updated_at"],
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at,
            "office": ticket.office.name,
            "service": ticket.service.name,
            "progress": projection["progress"],
        }
        return Response(TicketTrackingSerializer(payload).data)

    @action(detail=True, methods=["post"])
    def transition(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        serializer = TransitionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _ticket_action_error(
                request,
                code="invalid_transition",
                detail="Transition is invalid.",
                fields=_serializer_error_fields(serializer.errors),
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        actor = _authenticated_user(request)
        try:
            ticket = services.transition_ticket(
                ticket_id=ticket.id,
                actor=actor,
                expected_updated_at=serializer.validated_data["updated_at"],
                to_status_code=serializer.validated_data["to_status"],
                reason=serializer.validated_data.get("reason", ""),
                resolution_code=serializer.validated_data.get("resolution_code", ""),
                resolution_summary=serializer.validated_data.get("resolution_summary", ""),
                supervisor_id=serializer.validated_data.get("supervisor_id"),
                request=request,
            )
        except services.TransitionError as exc:
            return _ticket_action_error(
                request,
                code="invalid_transition",
                detail="Transition is invalid.",
                fields=exc.fields,
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        except services.TicketPermissionError:
            return _ticket_action_error(
                request,
                code="ticket_action_forbidden",
                detail="You cannot perform this ticket action.",
                fields={},
                response_status=status.HTTP_403_FORBIDDEN,
            )
        except services.TicketConflictError as exc:
            current = serializers.DateTimeField().to_representation(exc.current_updated_at)
            return _ticket_action_error(
                request,
                code="stale_ticket",
                detail="The ticket was updated by another user.",
                fields={"updated_at": [current]},
                response_status=status.HTTP_409_CONFLICT,
            )
        return Response(TicketDetailSerializer(ticket, context=self.get_serializer_context()).data)

    @action(
        detail=True,
        methods=["patch"],
        url_path="work-state",
        permission_classes=[IsAuthenticated, ScopePermission],
    )
    def work_state(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        serializer = WorkStateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _ticket_action_error(
                request,
                code="invalid_work_state",
                detail="Work state is invalid.",
                fields=_serializer_error_fields(serializer.errors),
                response_status=status.HTTP_400_BAD_REQUEST,
            )

        changes = dict(serializer.validated_data)
        expected_updated_at = changes.pop("updated_at")
        reason_value = changes.pop("reason", "")
        reason = reason_value if isinstance(reason_value, str) else ""
        actor = _authenticated_user(request)
        if "assignee" in changes and (changes.keys() - {"assignee"}):
            return _ticket_action_error(
                request,
                code="assignment_must_be_separate",
                detail="Assignment must be submitted separately.",
                fields={"assignee": ["Use the ticket assignment action for owner changes."]},
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            if "assignee" in changes:
                # One-release compatibility path; clients should use /assignment/.
                assignment_result = assign_ticket(
                    ticket_id=ticket.id,
                    actor=actor,
                    assignee_id=changes["assignee"],
                    expected_updated_at=expected_updated_at,
                    reason=reason,
                    request=request,
                )
                updated = assignment_result.ticket
            else:
                updated = services.update_work_state(
                    ticket_id=ticket.id,
                    actor=actor,
                    expected_updated_at=expected_updated_at,
                    changes=changes,
                    request=request,
                )
        except services.TicketScopeError as exc:
            raise NotFound from exc
        except services.TicketValidationError as exc:
            fields = dict(exc.fields)
            if "assignee" in changes and "assignee_id" in fields:
                fields["assignee"] = fields.pop("assignee_id")
            return _ticket_action_error(
                request,
                code="invalid_work_state",
                detail="Work state is invalid.",
                fields=fields,
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        except services.TicketPermissionError:
            return _ticket_action_error(
                request,
                code="ticket_action_forbidden",
                detail="You cannot perform this ticket action.",
                fields={},
                response_status=status.HTTP_403_FORBIDDEN,
            )
        except services.TicketConflictError as exc:
            current = serializers.DateTimeField().to_representation(exc.current_updated_at)
            return _ticket_action_error(
                request,
                code="stale_ticket",
                detail="The ticket was updated by another user.",
                fields={"updated_at": [current]},
                response_status=status.HTTP_409_CONFLICT,
            )
        return Response(
            TicketDetailSerializer(
                updated,
                context=self.get_serializer_context(),
            ).data
        )

    @action(detail=True, methods=["get"], url_path="assignees")
    def assignees(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        actor = _authenticated_user(request)
        if not can_assign(actor, ticket=ticket, request=request):
            return _ticket_action_error(
                request,
                code="ticket_action_forbidden",
                detail="You cannot perform this ticket action.",
                fields={},
                response_status=status.HTTP_403_FORBIDDEN,
            )
        search_serializer = AssigneeSearchSerializer(data=request.query_params)
        if not search_serializer.is_valid():
            return _ticket_action_error(
                request,
                code="invalid_assignee_search",
                detail="Assignee search is invalid.",
                fields=_serializer_error_fields(search_serializer.errors),
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        candidates = eligible_assignees(
            ticket,
            search=search_serializer.validated_data["search"],
        )
        return Response({"results": [_candidate_payload(item) for item in candidates]})

    @action(detail=True, methods=["get"], url_path="escalation-supervisors")
    def escalation_supervisors(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        actor = _authenticated_user(request)
        can_escalate = (
            available_transitions(
                ticket,
                actor,
                request=request,
            )
            .filter(to_status__code="escalated")
            .exists()
        )
        if not can_escalate:
            return _ticket_action_error(
                request,
                code="ticket_action_forbidden",
                detail="You cannot perform this ticket action.",
                fields={},
                response_status=status.HTTP_403_FORBIDDEN,
            )
        search_serializer = AssigneeSearchSerializer(data=request.query_params)
        if not search_serializer.is_valid():
            return _ticket_action_error(
                request,
                code="invalid_assignee_search",
                detail="Supervisor search is invalid.",
                fields=_serializer_error_fields(search_serializer.errors),
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        candidates = eligible_escalation_supervisors(
            ticket,
            search=search_serializer.validated_data["search"],
        )
        return Response({"results": [_candidate_payload(item) for item in candidates]})

    @action(detail=True, methods=["post"], url_path="assignment")
    def assignment(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        serializer = AssignmentRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _ticket_action_error(
                request,
                code="invalid_assignment",
                detail="Assignment is invalid.",
                fields=_serializer_error_fields(serializer.errors),
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        actor = _authenticated_user(request)
        try:
            result = assign_ticket(
                ticket_id=ticket.id,
                actor=actor,
                assignee_id=serializer.validated_data["assignee_id"],
                expected_updated_at=serializer.validated_data["expected_updated_at"],
                reason=serializer.validated_data.get("reason", ""),
                request=request,
            )
        except services.TicketScopeError as exc:
            raise NotFound from exc
        except services.TicketValidationError as exc:
            return _ticket_action_error(
                request,
                code="invalid_assignment",
                detail="Assignment is invalid.",
                fields=exc.fields,
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        except services.TicketPermissionError:
            return _ticket_action_error(
                request,
                code="ticket_action_forbidden",
                detail="You cannot perform this ticket action.",
                fields={},
                response_status=status.HTTP_403_FORBIDDEN,
            )
        except services.TicketConflictError as exc:
            current = serializers.DateTimeField().to_representation(exc.current_updated_at)
            return _ticket_action_error(
                request,
                code="stale_ticket",
                detail="The ticket was updated by another user.",
                fields={"updated_at": [current]},
                response_status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "ticket": TicketDetailSerializer(
                    result.ticket,
                    context=self.get_serializer_context(),
                ).data,
                "receipt": AssignmentReceiptSerializer(result.receipt).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="routing")
    def routing(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        serializer = QueueRoutingRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _ticket_action_error(
                request,
                code="invalid_routing",
                detail="Routing is invalid.",
                fields=_serializer_error_fields(serializer.errors),
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        actor = _authenticated_user(request)
        try:
            result = route_ticket(
                ticket_id=ticket.id,
                actor=actor,
                queue_id=serializer.validated_data["queue_id"],
                assignee_id=serializer.validated_data["assignee_id"],
                expected_updated_at=serializer.validated_data["updated_at"],
                reason=serializer.validated_data["reason"],
                request=request,
            )
        except services.TicketScopeError as exc:
            raise NotFound from exc
        except services.TicketValidationError as exc:
            return _ticket_action_error(
                request,
                code="invalid_routing",
                detail="Routing is invalid.",
                fields=exc.fields,
                response_status=status.HTTP_400_BAD_REQUEST,
            )
        except services.TicketPermissionError:
            return _ticket_action_error(
                request,
                code="ticket_action_forbidden",
                detail="You cannot perform this ticket action.",
                fields={},
                response_status=status.HTTP_403_FORBIDDEN,
            )
        except services.TicketConflictError as exc:
            current = serializers.DateTimeField().to_representation(exc.current_updated_at)
            return _ticket_action_error(
                request,
                code="stale_ticket",
                detail="The ticket was updated by another user.",
                fields={"updated_at": [current]},
                response_status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "ticket": TicketDetailSerializer(
                    result.ticket,
                    context=self.get_serializer_context(),
                ).data,
                "receipt": RoutingReceiptSerializer(result.receipt).data,
            }
        )

    @action(detail=True, methods=["get"], url_path="activity")
    def activity(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        return Response({"results": build_ticket_activity(ticket, request=request)})

    @action(detail=True, methods=["get", "post"], url_path="messages")
    def messages(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        if request.method == "GET":
            from .api import TicketMessageSerializer

            return Response(
                {"results": TicketMessageSerializer(ticket.messages.all(), many=True).data}
            )
        ser = MessageCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = _authenticated_user(request)
        if not can_add_ticket_content(actor, ticket, request=request):
            raise PermissionDenied(
                detail="You cannot perform this ticket action.",
                code="ticket_action_forbidden",
            )
        try:
            msg = services.add_message(
                ticket=ticket,
                actor=actor,
                request=request,
                direction="outbound",
                actor_subject=actor.keycloak_subject,
                author_subject=actor.keycloak_subject,
                author_label=actor.display_name or actor.username,
                body_text=ser.validated_data["body_text"],
                body_html=ser.validated_data.get("body_html", ""),
                template_key=ser.validated_data.get("template_key", ""),
                template_version=ser.validated_data.get("template_version", ""),
            )
        except services.TicketScopeError as exc:
            raise NotFound from exc
        except services.TicketPermissionError:
            raise PermissionDenied(
                detail="You cannot perform this ticket action.",
                code="ticket_action_forbidden",
            ) from None
        return Response({"id": str(msg.id)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="notes")
    def notes(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
        ticket = self.get_object()
        if request.method == "GET":
            from .api import TicketNoteSerializer

            return Response({"results": TicketNoteSerializer(ticket.notes.all(), many=True).data})
        ser = NoteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = _authenticated_user(request)
        if not can_add_ticket_content(actor, ticket, request=request):
            raise PermissionDenied(
                detail="You cannot perform this ticket action.",
                code="ticket_action_forbidden",
            )
        try:
            note = services.add_internal_note(
                ticket=ticket,
                actor=actor,
                request=request,
                body=ser.validated_data["body"],
                author_subject=actor.keycloak_subject,
            )
        except services.TicketScopeError as exc:
            raise NotFound from exc
        except services.TicketPermissionError:
            raise PermissionDenied(
                detail="You cannot perform this ticket action.",
                code="ticket_action_forbidden",
            ) from None
        return Response({"id": str(note.id)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="it-child")
    def it_child(
        self,
        request: Request,
        number: str | None = None,
    ) -> Response:
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
        actor = _authenticated_user(request)
        try:
            child = create_it_child_ticket(
                parent=parent,
                summary=summary,
                technical_priority=priority,
                carry_matter_reference=carry,
                actor=actor,
                request=request,
            )
        except services.TicketScopeError as exc:
            raise NotFound from exc
        except services.TicketPermissionError:
            raise PermissionDenied(
                detail="You cannot perform this ticket action.",
                code="ticket_action_forbidden",
            ) from None
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
    def kanban(self, request: Request) -> Response:
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
        grouped: dict[str, list[object]] = {}
        from .api import TicketListSerializer

        for ticket in qs.order_by("priority", "-created_at")[:300]:
            code = ticket.status.code
            grouped.setdefault(code, []).append(
                TicketListSerializer(
                    ticket,
                    context=self.get_serializer_context(),
                ).data
            )
        return Response({"columns": grouped})


@api_view(["POST"])
@permission_classes([IsAuthenticated, ScopePermission])
def public_intake(request: Request) -> Response:
    """Create a ticket from an authenticated staff intake channel."""
    from apps.catalogue.models import RequestType, Service
    from apps.organisations.models import Office

    actor = _authenticated_user(request)
    attach_scopes(request)
    if not has_unrestricted_domain_scope(
        actor,
        "operational",
        request=request,
    ):
        raise PermissionDenied(
            detail="Operational intake permission required.",
            code="intake_forbidden",
        )

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
        return Response(
            {"detail": "Invalid service or office.", "code": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    required_scope = Scope(
        domain="operational",
        office_id=str(office.id),
        service_id=str(service.id),
    )
    actor_scopes = getattr(actor, "_scopes", ())
    if not any(
        isinstance(scope, Scope) and scope.queue_id is None and scope.matches(required_scope)
        for scope in actor_scopes
    ):
        raise PermissionDenied(
            detail=(
                "Operational intake permission required for this service and office "
                "without a queue restriction."
            ),
            code="intake_forbidden",
        )

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
        title=_clean_public_text(data["title"])[:255],
        description=_clean_public_text(data["description"]),
        requester=contact,
        service=service,
        request_type=request_type,
        office=office,
        channel=data.get("channel") or "web",
        matter_reference=data.get("matter_reference", ""),
        actor_subject=actor.keycloak_subject,
        actor=actor,
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
def operational_dashboard(request: Request) -> Response:
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

    return Response(
        {
            "totals": {
                "open": qs.exclude(
                    status__code__in=[
                        "closed",
                        "resolved",
                        "cancelled",
                        "rejected",
                        "duplicate",
                        "spam",
                    ]
                ).count(),
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
            "unassigned": qs.filter(assignee__isnull=True)
            .exclude(
                status__code__in=[
                    "closed",
                    "resolved",
                    "cancelled",
                    "rejected",
                    "duplicate",
                    "spam",
                ]
            )
            .count(),
            "breached_sla": qs.filter(sla_instances__state="breached").distinct().count(),
        }
    )
