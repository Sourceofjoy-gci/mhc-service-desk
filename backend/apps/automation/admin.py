from django.contrib import admin

from .models import AutomationExecution, AutomationRule

admin.site.register(AutomationRule)
admin.site.register(AutomationExecution)
