from django.contrib import admin
from django.http import HttpRequest

from .models import (
    OutboxEvent,
    Ticket,
    TicketCustodyEvent,
    TicketLink,
    TicketMessage,
    TicketNote,
    Watcher,
)

admin.site.register(Ticket)
admin.site.register(TicketMessage)
admin.site.register(TicketNote)
admin.site.register(TicketLink)
admin.site.register(Watcher)
admin.site.register(OutboxEvent)


@admin.register(TicketCustodyEvent)
class TicketCustodyEventAdmin(admin.ModelAdmin):
    list_display = (
        "ticket",
        "sequence",
        "event_type",
        "occurred_at",
        "actor_display_name",
    )
    readonly_fields = tuple(field.name for field in TicketCustodyEvent._meta.fields)

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
