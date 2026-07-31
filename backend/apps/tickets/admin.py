from typing import TYPE_CHECKING

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.identity_access.scope import scope_ticket_queryset

from .models import (
    OutboxEvent,
    Ticket,
    TicketCustodyEvent,
    TicketLink,
    TicketMessage,
    TicketNote,
    Watcher,
)

admin.site.register(TicketMessage)
admin.site.register(TicketNote)
admin.site.register(TicketLink)
admin.site.register(Watcher)
admin.site.register(OutboxEvent)


TICKET_CUSTODY_CONTROLLED_FIELDS = (
    "domain",
    "status",
    "priority",
    "channel",
    "service",
    "request_type",
    "office",
    "queue",
    "assignee",
    "team",
    "confidentiality",
    "waiting_reason",
    "blocked_reason",
    "next_action",
    "next_action_at",
    "resolution_code",
    "resolution_summary",
    "acknowledged_at",
    "first_responded_at",
    "resolved_at",
    "closed_at",
    "reopened_at",
)


if TYPE_CHECKING:

    class _TicketAdminBase(admin.ModelAdmin[Ticket]):
        pass

    class _TicketCustodyEventAdminBase(admin.ModelAdmin[TicketCustodyEvent]):
        pass

else:
    _TicketAdminBase = admin.ModelAdmin
    _TicketCustodyEventAdminBase = admin.ModelAdmin


@admin.register(Ticket)
class TicketAdmin(_TicketAdminBase):
    """Keep custody-controlled writes behind ticket domain services."""

    readonly_fields = TICKET_CUSTODY_CONTROLLED_FIELDS

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Ticket | None = None
    ) -> bool:
        return False


@admin.register(TicketCustodyEvent)
class TicketCustodyEventAdmin(_TicketCustodyEventAdminBase):
    list_display = (
        "ticket_reference",
        "sequence",
        "event_type",
        "occurred_at",
        "actor_display_name",
    )
    list_display_links = None
    readonly_fields = (
        "ticket_reference",
        *(field.name for field in TicketCustodyEvent._meta.fields if field.name != "ticket"),
    )
    fields = readonly_fields

    @admin.display(description="ticket")
    def ticket_reference(self, obj: TicketCustodyEvent) -> str:
        return obj.ticket.number

    def get_queryset(self, request: HttpRequest) -> QuerySet[TicketCustodyEvent]:
        queryset = super().get_queryset(request)
        visible_tickets = scope_ticket_queryset(request.user, Ticket.objects.all(), request=request)
        return queryset.filter(ticket__in=visible_tickets).select_related("ticket")

    def has_view_permission(
        self, request: HttpRequest, obj: TicketCustodyEvent | None = None
    ) -> bool:
        if not super().has_view_permission(request, obj):
            return False
        if obj is None:
            return True
        return scope_ticket_queryset(
            request.user,
            Ticket.objects.filter(pk=obj.ticket_id),
            request=request,
        ).exists()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: TicketCustodyEvent | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: TicketCustodyEvent | None = None
    ) -> bool:
        return False
