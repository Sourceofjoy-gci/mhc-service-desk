from django.contrib import admin

from .models import CustomFieldDefinition, RequestType, Service

admin.site.register(Service)
admin.site.register(RequestType)
admin.site.register(CustomFieldDefinition)
