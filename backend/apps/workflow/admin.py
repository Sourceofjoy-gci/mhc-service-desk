from django.contrib import admin

from .models import Status, Transition, TransitionHistory

admin.site.register(Status)
admin.site.register(Transition)
admin.site.register(TransitionHistory)
