"""DRF serializers for the tickets app.

Serializers handle field-level masking (PRD §23.1) and field validation.
Views handle authorisation; the two responsibilities are kept separate.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.contacts.api import ContactSerializer
from apps.files.views import attachment_metadata
from apps.identity_access.scope import get_authority_snapshot
from apps.sla.serializers import serialize_sla_clocks
from apps.workflow.models import Status

from .activity import scoped_ticket_relationships
from .models import Ticket, TicketLink, TicketMessage, TicketNote
from .permissions import (
    can_add_ticket_content,
    can_change_confidentiality,
    can_reassign,
    can_update_work_state,
)
from .workflow import available_transitions


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

    def get_capabilities(self, obj: Ticket) -> dict[str, bool | str | None]:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return {
                "can_update_work_state": False,
                "can_self_assign": False,
                "self_assignee_id": None,
                "can_reassign": False,
                "can_change_confidentiality": False,
                "can_add_message": False,
                "can_add_note": False,
                "can_upload_attachment": False,
            }

        can_update = can_update_work_state(user, obj, request=request)
        can_add_content = can_add_ticket_content(user, obj, request=request)
        can_self_assign = can_update and obj.assignee_id is None
        return {
            "can_update_work_state": can_update,
            "can_self_assign": can_self_assign,
            "self_assignee_id": str(user.id) if can_self_assign else None,
            "can_reassign": can_reassign(user, ticket=obj, request=request),
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
    team = serializers.CharField(required=False, allow_blank=True, max_length=128)
    waiting_reason = serializers.CharField(required=False, allow_blank=True, max_length=64)
    blocked_reason = serializers.CharField(required=False, allow_blank=True)
    next_action = serializers.CharField(required=False, allow_blank=True, max_length=255)
    next_action_at = serializers.DateTimeField(required=False, allow_null=True)
    confidentiality = serializers.ChoiceField(
        required=False,
        choices=Ticket.Confidentiality.choices,
    )


class PublicIntakeSerializer(serializers.Serializer[dict[str, object]]):
    """Public form intake (FR-002, FR-003, FR-005, FR-073).

    No authentication required. Rate-limited at the view layer.

    ``channel`` lets the agent SPA pass the originating channel (call, walk_in,
    web, email) when creating a ticket on behalf of a requester.
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
