from django.contrib import admin

from .models import WhatsappAccount, WhatsappMessage

admin.site.register(WhatsappAccount)
admin.site.register(WhatsappMessage)
