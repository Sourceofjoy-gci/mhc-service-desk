from django.contrib import admin

from .models import EmailDelivery, Mailbox

admin.site.register(Mailbox)
admin.site.register(EmailDelivery)
