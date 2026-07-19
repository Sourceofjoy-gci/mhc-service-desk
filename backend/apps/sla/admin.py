from django.contrib import admin

from .models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy

admin.site.register(BusinessCalendar)
admin.site.register(SlaPolicy)
admin.site.register(SlaInstance)
admin.site.register(SlaPauseHistory)
