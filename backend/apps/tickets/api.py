"""DRF serializers for the tickets app.

Serializers handle field-level masking (PRD §23.1) and field validation.
Views handle authorisation; the two responsibilities are kept separate.
"""
from __future__ import annotations

import re

from rest_framework import serializers

from apps.contacts.api import ContactSerializer
from apps.files.views import attachment_metadata
from apps.identity_access.scope import get_authority_snapshot
from apps.sla.serializers import serialize_sla_clocks
from apps.workflow.models import Status

from .activity import scoped_ticket_relationships
from .assignment import (
    AssignmentActor,
    AssignmentParty,
    AssignmentReceipt,
    RoutingReceipt,
)
from .custody import CustodyQueue
from .eligibility import custody_party_for_user, is_eligible_assignee
from .models import Ticket, TicketLink, TicketMessage, TicketNote
from .permissions import (
    can_add_ticket_content,
    can_assign,
    can_change_confidentiality,
    can_update_work_state,
)
from .tracking import TrackingStatus
from .workflow import available_transitions


class TicketTrackingLookupSerializer(serializers.Serializer[dict[str, str]]):
    reference = serializers.CharField()

    def validate_reference(self, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z][0-9]{5}", normalized):
            raise serializers.ValidationError("Enter a valid ticket reference.")
        return normalized


class TrackingProgressSerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.ChoiceField(
        choices=[status.value for status in TrackingStatus]
    )
    occurred_at = serializers.DateTimeField()


class TicketTrackingSerializer(serializers.Serializer[dict[str, object]]):
    reference = serializers.CharField()
    title = serializers.CharField()
    tracking_status = serializers.ChoiceField(
        choices=[status.value for status in TrackingStatus]
    )
    status_updated_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    office = serializers.CharField()
    service = serializers.CharField()
    progress = TrackingProgressSerializer(many=True)


class StatusRefSerializer(serializers.ModelSerializer[Status]):
    class Meta:
        model = Status
        fields = ("id", "code", "name", "public_label", "is_terminal", "is_initial", "order")


class TicketMessageSerializer(serializers.ModelSerializer[TicketMessage]):
    class Meta:
        model = TicketMessage
        fields = (
            "id", "direction", "author_label", "body_text", "body_html_sanitized",
            "template_key", "template_version", "delivery_status", "created_at",
        )
        read_only_fields = fields


class TicketNoteSerializer(serializers.ModelSerializer[TicketNote]):
    class Meta:
        model = TicketNote
        fields = ("id", "author_subject", "body", "created_at")
        read_only_fields = ("id", "created_at")


class TicketLinkSerializer(serializers.ModelSerializer[TicketLink]):
    class Meta:
        model = TicketLink
        fields = ("id", "to_ticket", "kind", "created_at")
        read_only_fields = ("id", "created_at")


class TicketListSerializer(serializers.ModelSerializer[Ticket]):
    """Compact view used in queues, Kanban and search results (FR-042)."""

    status_code = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    status_public = serializers.CharField(source="status.public_label", read_only=True)
    requester_name = serializers.CharField(source="requester.full_name", read_only=True)
    office_code = serializers.CharField(source="office.code", read_only=True)
    service_code = serializers.CharField(source="service.code", read_only=True)
    age_hours = serializers.SerializerMethodField()
    sla_health = serializers.SerializerMethodField()
    available_transition_codes = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields: tuple[str, ...] = (
            "id", "number", "domain", "title", "channel", "priority", "confidentiality",
            "status_code", "status_name", "status_public",
            "requester_name", "office_code", "service_code",
            "assignee", "waiting_reason", "created_at", "updated_at",
            "age_hours", "sla_health", "available_transition_codes",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_age_hours(self, obj: Ticket) -> float:
        from django.utils import timezone
        delta = timezone.now() - obj.created_at
        return round(delta.total_seconds() / 3600, 1)

    def get_sla_health(self, obj: Ticket) -> str:
        # Compressed view: worst active SLA instance
        from apps.sla.models import SlaInstance
        inst = (
            SlaInstance.objects.filter(
                ticket=obj,
                state__in=[
                    "active",
                    "paused_requester",
                    "paused_internal",
                    "paused_it",
                ],
            )
            .order_by("due_at")
            .first()
        )
        if not inst:
            return "none"
        if inst.state != "active":
            return "paused"
        if inst.state == "breached":
            return "breached"
        from django.utils import timezone
        if inst.due_at < timezone.now():
            return "breached"
        # consumption percent is a stub; full impl reads consumed_business_seconds
        return "on_track"

    def get_available_transition_codes(self, obj: Ticket) -> list[str]:
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        return [
            transition.to_status.code
            for transition in available_transitions(obj, actor, request=request)
        ]


class TicketDetailSerializer(TicketListSerializer):
    description = serializers.CharField()
    requester = ContactSerializer(read_only=True)
    organisation = serializers.CharField(
        source="organisation.name",
        read_only=True,
        allow_null=True,
    )
    service = serializers.CharField(source="service.name", read_only=True)
    request_type = serializers.CharField(source="request_type.name", read_only=True)
    office = serializers.CharField(source="office.name", read_only=True)
    matter_reference = serializers.CharField()
    tags = serializers.JSONField()
    custom_fields = serializers.JSONField()
    resolution_code = serializers.CharField()
    resolution_summary = serializers.CharField()
    acknowledged_at = serializers.DateTimeField(read_only=True)
    first_responded_at = serializers.DateTimeField(read_only=True)
    resolved_at = serializers.DateTimeField(read_only=True)
    closed_at = serializers.DateTimeField(read_only=True)
    messages = TicketMessageSerializer(many=True, read_only=True)
    notes = TicketNoteSerializer(many=True, read_only=True)
    links = TicketLinkSerializer(many=True, read_only=True)
    assignee_detail = serializers.SerializerMethodField()
    relationships = serializers.SerializerMethodField()
    sla_clocks = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()
    available_transitions = serializers.SerializerMethodField()

    def get_assignee_detail(self, obj: Ticket) -> dict[str, str] | None:
        assignee = obj.assignee
        if assignee is None:
            return None
        return {
            "id": str(obj.assignee_id),
            "display_name": assignee.display_name or assignee.username,
        }

    def get_relationships(self, obj: Ticket) -> list[dict[str, str]]:
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if actor is None or not actor.is_authenticated:
            return []
        snapshot = get_authority_snapshot(actor, request=request)
        scoped_links = scoped_ticket_relationships(
            obj,
            actor,
            request=request,
            snapshot=snapshot,
        )
        relationships = [
            {
                "id": str(link.id),
                "kind": link.kind,
                "ticket_number": link.to_ticket.number,
                "direction": "outgoing",
            }
            for link in scoped_links
            if link.from_ticket_id == obj.id
        ]
        relationships.extend(
            {
                "id": str(link.id),
                "kind": link.kind,
                "ticket_number": link.from_ticket.number,
                "direction": "incoming",
            }
            for link in scoped_links
            if link.to_ticket_id == obj.id
        )
        return sorted(relationships, key=lambda relationship: relationship["id"])

    def get_sla_clocks(self, obj: Ticket) -> dict[str, object]:
        return serialize_sla_clocks(obj)

    def get_attachments(self, obj: Ticket) -> list[dict[str, object]]:
        return [attachment_metadata(item) for item in obj.attachments.all()]

    def get_capabilities(self, obj: Ticket) -> dict[str, object]:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return {
                "can_update_work_state": False,
                "can_self_assign": False,
                "self_assignee_id": None,
                "self_assignee_detail": None,
                "can_assign": False,
                "can_reassign": False,
                "can_change_confidentiality": False,
                "can_add_message": False,
                "can_add_note": False,
                "can_upload_attachment": False,
            }

        can_update = can_update_work_state(user, obj, request=request)
        can_add_content = can_add_ticket_content(user, obj, request=request)
        can_self_assign = (
            can_update
            and obj.assignee_id is None
            and is_eligible_assignee(obj, user)
        )
        self_assignee_detail = None
        if can_self_assign:
            party = custody_party_for_user(obj, user)
            self_assignee_detail = {
                "id": party.id,
                "username": user.username,
                "display_name": party.display_name,
                "designations": list(party.designations),
                "team_labels": list(party.team_labels),
            }
        can_assign_ticket = can_assign(user, ticket=obj, request=request)
        return {
            "can_update_work_state": can_update,
            "can_self_assign": can_self_assign,
            "self_assignee_id": str(user.id) if can_self_assign else None,
            "self_assignee_detail": self_assignee_detail,
            "can_assign": can_assign_ticket,
            "can_reassign": can_assign_ticket,
            "can_change_confidentiality": can_change_confidentiality(
                user,
                ticket=obj,
                request=request,
            ),
            "can_add_message": can_add_content,
            "can_add_note": can_add_content,
            "can_upload_attachment": can_add_content,
        }

    def get_available_transitions(self, obj: Ticket) -> list[dict[str, object]]:
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        return [
            {
                "to_status": transition.to_status.code,
                "label": transition.name,
                "requires_resolution": transition.sets_resolution,
                "requires_reason": "reason" in transition.required_fields,
            }
            for transition in available_transitions(obj, actor, request=request)
        ]

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + (
            "description", "requester", "organisation", "service", "request_type", "office",
            "matter_reference", "tags", "custom_fields",
            "team", "blocked_reason", "next_action", "next_action_at",
            "resolution_code", "resolution_summary",
            "acknowledged_at", "first_responded_at", "resolved_at", "closed_at",
            "reopened_at", "assignee_detail", "relationships", "sla_clocks",
            "attachments", "messages", "notes", "links", "capabilities",
            "available_transitions",
        )


class TransitionRequestSerializer(serializers.Serializer[dict[str, object]]):
    to_status = serializers.CharField()
    updated_at = serializers.DateTimeField()
    reason = serializers.CharField(required=False, allow_blank=True)
    resolution_code = serializers.CharField(required=False, allow_blank=True)
    resolution_summary = serializers.CharField(required=False, allow_blank=True)
    supervisor_id = serializers.UUIDField(required=False)


class MessageCreateSerializer(serializers.Serializer[dict[str, object]]):
    body_text = serializers.CharField()
    body_html = serializers.CharField(required=False, allow_blank=True)
    template_key = serializers.CharField(required=False, allow_blank=True)
    template_version = serializers.CharField(required=False, allow_blank=True)


class NoteCreateSerializer(serializers.Serializer[dict[str, object]]):
    body = serializers.CharField()


class WorkStateRequestSerializer(serializers.Serializer[dict[str, object]]):
    updated_at = serializers.DateTimeField()
    assignee = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
    )
    team = serializers.CharField(required=False, allow_blank=True, max_length=128)
    waiting_reason = serializers.CharField(required=False, allow_blank=True, max_length=64)
    blocked_reason = serializers.CharField(required=False, allow_blank=True)
    next_action = serializers.CharField(required=False, allow_blank=True, max_length=255)
    next_action_at = serializers.DateTimeField(required=False, allow_null=True)
    confidentiality = serializers.ChoiceField(
        required=False,
        choices=Ticket.Confidentiality.choices,
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if "reason" in attrs and "assignee" not in attrs:
            raise serializers.ValidationError(
                {"reason": ["This field is only valid with assignee."]}
            )
        return attrs


class AssigneeSearchSerializer(serializers.Serializer[dict[str, object]]):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=100,
    )


class AssignmentRequestSerializer(serializers.Serializer[dict[str, object]]):
    assignee_id = serializers.UUIDField(allow_null=True)
    expected_updated_at = serializers.DateTimeField()
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
    )


class AssignmentPartySerializer(serializers.Serializer[AssignmentParty]):
    id = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    designations = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    team_labels = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )


class AssignmentActorSerializer(serializers.Serializer[AssignmentActor]):
    kind = serializers.CharField(read_only=True)
    subject = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)


class AssignmentReceiptSerializer(serializers.Serializer[AssignmentReceipt]):
    ticket_number = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    previous_assignee = AssignmentPartySerializer(read_only=True, allow_null=True)
    new_assignee = AssignmentPartySerializer(read_only=True, allow_null=True)
    occurred_at = serializers.DateTimeField(read_only=True)
    performed_by = AssignmentActorSerializer(read_only=True)


class QueueRoutingRequestSerializer(serializers.Serializer[dict[str, object]]):
    queue_id = serializers.UUIDField(allow_null=True)
    assignee_id = serializers.UUIDField(allow_null=True)
    updated_at = serializers.DateTimeField()
    reason = serializers.CharField(max_length=1000, allow_blank=False)


class CustodyQueueSerializer(serializers.Serializer[CustodyQueue]):
    id = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True, allow_null=True)  # type: ignore[assignment]


class RoutingReceiptSerializer(serializers.Serializer[RoutingReceipt]):
    ticket_number = serializers.CharField(read_only=True)
    previous_queue = CustodyQueueSerializer(read_only=True, allow_null=True)
    new_queue = CustodyQueueSerializer(read_only=True, allow_null=True)
    previous_assignee = AssignmentPartySerializer(read_only=True, allow_null=True)
    new_assignee = AssignmentPartySerializer(read_only=True, allow_null=True)
    occurred_at = serializers.DateTimeField(read_only=True)
    performed_by = AssignmentActorSerializer(read_only=True)


class PublicIntakeSerializer(serializers.Serializer[dict[str, object]]):
    """Staff-assisted intake while the public form is disabled.

    Authentication and an applicable Operational scope are required.

    ``channel`` lets the agent SPA pass the originating channel (call, walk_in,
    web, email) when creating a ticket on behalf of a requester. The web form
    route is not exposed in the current phase.
    """

    request_type_code = serializers.CharField()
    service_code = serializers.CharField()
    office_code = serializers.CharField()
    title = serializers.CharField(max_length=255)
    description = serializers.CharField()
    requester_name = serializers.CharField(max_length=255)
    requester_email = serializers.EmailField(required=False, allow_blank=True)
    requester_phone = serializers.CharField(required=False, allow_blank=True, max_length=32)
    matter_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    consent = serializers.BooleanField()
    channel = serializers.ChoiceField(
        choices=["web", "call", "walk_in", "email"],
        required=False,
        default="web",
    )
    attachments = serializers.ListField(
        child=serializers.FileField(), required=False, allow_empty=True, max_length=5
    )
