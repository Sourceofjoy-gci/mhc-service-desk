from django.contrib import admin

from .models import OutboxEvent, Ticket, TicketLink, TicketMessage, TicketNote, Watcher

admin.site.register(Ticket)
admin.site.register(TicketMessage)
admin.site.register(TicketNote)
admin.site.register(TicketLink)
admin.site.register(Watcher)
admin.site.register(OutboxEvent)
