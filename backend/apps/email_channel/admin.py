from django.contrib import admin

from .models import Mailbox, EmailDelivery

admin.site.register(Mailbox)
admin.site.register(EmailDelivery)
