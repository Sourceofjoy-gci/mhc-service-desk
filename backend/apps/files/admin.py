from django.contrib import admin

from .models import Attachment, AttachmentAccessLog

admin.site.register(Attachment)
admin.site.register(AttachmentAccessLog)
