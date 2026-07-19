"""DRF serializers for the tickets app.

Serializers handle field-level masking (PRD §23.1) and field validation.
Views handle authorisation; the two responsibilities are kept separate.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.contacts.api import ContactSerializer
from apps.workflow.models import Status

from .models import OutboxEvent, Ticket, TicketLink, TicketMessage, TicketNote, Watcher


class StatusRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Status
        fields = ("id", "code", "name", "public_label", "is_terminal", "is_initial", "order")


class TicketMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketMessage
        fields = (
            "id", "direction", "author_label", "body_text", "body_html_sanitized",
            "template_key", "template_version", "delivery_status", "created_at",
        )
        read_only_fields = fields


class TicketNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketNote
        fields = ("id", "author_subject", "body", "created_at")
        read_only_fields = ("id", "created_at")


class TicketLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketLink
        fields = ("id", "to_ticket", "kind", "created_at")
        read_only_fields = ("id", "created_at")


class TicketListSerializer(serializers.ModelSerializer):
    """Compact view used in queues, Kanban and search results (FR-042)."""

    status_code = serializers.CharField(source="status.code", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    status_public = serializers.CharField(source="status.public_label", read_only=True)
    requester_name = serializers.CharField(source="requester.full_name", read_only=True)
    office_code = serializers.CharField(source="office.code", read_only=True)
    service_code = serializers.CharField(source="service.code", read_only=True)
    age_hours = serializers.SerializerMethodField()
    sla_health = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = (
            "id", "number", "domain", "title", "channel", "priority", "confidentiality",
            "status_code", "status_name", "status_public",
            "requester_name", "office_code", "service_code",
            "assignee", "waiting_reason", "created_at", "updated_at",
            "age_hours", "sla_health",
        )
        read_only_fields = fields

    def get_age_hours(self, obj: Ticket) -> float:
        from django.utils import timezone
        delta = timezone.now() - obj.created_at
        return round(delta.total_seconds() / 3600, 1)

    def get_sla_health(self, obj: Ticket) -> str:
        # Compressed view: worst active SLA instance
        from apps.sla.models import SlaInstance
        inst = (
            SlaInstance.objects.filter(ticket=obj, state__in=["active", "paused_requester", "paused_internal", "paused_it"])
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


class TicketDetailSerializer(TicketListSerializer):
    description = serializers.CharField()
    requester = ContactSerializer(read_only=True)
    organisation = serializers.CharField(source="organisation.name", read_only=True, allow_null=True)
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

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + (
            "description", "requester", "organisation", "service", "request_type", "office",
            "matter_reference", "tags", "custom_fields",
            "resolution_code", "resolution_summary",
            "acknowledged_at", "first_responded_at", "resolved_at", "closed_at",
            "messages", "notes", "links",
        )


class TransitionRequestSerializer(serializers.Serializer):
    to_status = serializers.CharField()
    reason = serializers.CharField(required=False, allow_blank=True)
    resolution_code = serializers.CharField(required=False, allow_blank=True)
    resolution_summary = serializers.CharField(required=False, allow_blank=True)


class MessageCreateSerializer(serializers.Serializer):
    body_text = serializers.CharField()
    body_html = serializers.CharField(required=False, allow_blank=True)
    template_key = serializers.CharField(required=False, allow_blank=True)
    template_version = serializers.CharField(required=False, allow_blank=True)


class NoteCreateSerializer(serializers.Serializer):
    body = serializers.CharField()


class PublicIntakeSerializer(serializers.Serializer):
    """Public form intake (FR-002, FR-003, FR-005, FR-073).

    No authentication required. Rate-limited at the view layer.
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
    attachments = serializers.ListField(
        child=serializers.FileField(), required=False, allow_empty=True, max_length=5
    )
